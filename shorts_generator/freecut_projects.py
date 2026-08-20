"""Auto-create and update FreeCut projects in the workspace.

FreeCut (vendor/freecut) is a browser video editor whose workspace lives on
disk: projects at `projects/<id>/project.json` (listed in `index.json`) and
media at `media/<id>/metadata.json` + `media/<id>/<filename>` (linked to a
project via `projects/<id>/media-links.json`).

This module mirrors those on-disk structures from Python so that every time a
video gets clipped into shorts, a project named after the YouTube title shows
up in FreeCut with the shorts already registered in its media library.

Everything here is best-effort: if any write fails, the caller's clip
generation must still succeed. Functions return None / [] on failure and never
raise.
"""
import json
import os
import random
import shutil
import string
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# 8-char base62 id, matching FreeCut's `generateProjectId()`.
_PROJECT_ID_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase
_PROJECT_ID_LEN = 8

# FreeCut's CURRENT_SCHEMA_VERSION (vendor/freecut/src/shared/projects/migrations/types.ts).
CURRENT_SCHEMA_VERSION = 15

_INDEX_VERSION = "1.0"
_LINKS_VERSION = "1.0"

# FreeCut's AI-output envelope schema (vendor/freecut/src/infrastructure/
# storage/workspace-fs/ai-outputs/types.ts). Transcripts are stored per media
# at `media/<id>/cache/ai/transcript.json` and shown in the editor's Transcript
# sidebar tab. Words must be timed in media-native seconds so the editor's
# playhead highlight stays in sync with the short's own timeline.
_AI_OUTPUT_SCHEMA_VERSION = 1

# faster-whisper model name -> FreeCut MediaTranscriptModel (types/storage.ts).
_WHISPER_MODEL_MAP = {
    "tiny": "whisper-tiny",
    "base": "whisper-base",
    "small": "whisper-small",
    "medium": "whisper-large",
    "large": "whisper-large",
    "large-v1": "whisper-large",
    "large-v2": "whisper-large",
    "large-v3": "whisper-large",
    "turbo": "whisper-large",
}

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _now_ms() -> int:
    return int(__import__("time").time() * 1000)


def _read_json(path: Path) -> Optional[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _generate_project_id() -> str:
    return "".join(random.choice(_PROJECT_ID_CHARS) for _ in range(_PROJECT_ID_LEN))


def _probe_duration(path: Path) -> float:
    """Best-effort ffprobe duration in seconds; 0.0 on any failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=30,
        )
        if r.returncode == 0:
            return float(r.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    return 0.0


def _make_thumbnail(path: Path, media_dir: Path) -> None:
    """Extract a frame as media/<id>/thumbnail.jpg (best-effort)."""
    thumb = media_dir / "thumbnail.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5",
             "-i", str(path), "-frames:v", "1",
             "-vf", "scale=320:-1", str(thumb)],
            capture_output=True, text=True, creationflags=_NO_WINDOW, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        pass


# ── index.json ──────────────────────────────────────────────────────

def _read_index(workspace: Path) -> Dict:
    return _read_json(workspace / "index.json") or {"version": _INDEX_VERSION, "updatedAt": 0, "projects": []}


def _write_index(workspace: Path, index: Dict) -> None:
    projects = index.get("projects") or []
    projects.sort(key=lambda e: e.get("updatedAt", 0), reverse=True)
    _write_json(workspace / "index.json", {
        "version": _INDEX_VERSION,
        "updatedAt": _now_ms(),
        "projects": projects,
    })


# ── project.json ────────────────────────────────────────────────────

def _find_project_for_video(workspace: Path, video_id: str) -> Optional[str]:
    """Return the id of an existing project whose sourceVideoId matches."""
    projects_dir = workspace / "projects"
    if not projects_dir.is_dir():
        return None
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        project = _read_json(entry / "project.json")
        if project and project.get("sourceVideoId") == video_id:
            return entry.name
    return None


def _load_project(workspace: Path, project_id: str) -> Optional[Dict]:
    return _read_json(workspace / "projects" / project_id / "project.json")


def _write_project(workspace: Path, project: Dict) -> None:
    project_dir = workspace / "projects" / str(project["id"])
    _write_json(project_dir / "project.json", project)


def _project_object(project_id: str, name: str, video_id: str) -> Dict:
    return {
        "id": project_id,
        "name": name,
        "description": "",
        "metadata": {"width": 1080, "height": 1920, "fps": 30},
        "createdAt": _now_ms(),
        "updatedAt": _now_ms(),
        "duration": 0,
        "schemaVersion": CURRENT_SCHEMA_VERSION,
        "sourceVideoId": video_id,
    }


# ── media ───────────────────────────────────────────────────────────

def _media_dir(workspace: Path, media_id: str) -> Path:
    return workspace / "media" / media_id


def _find_media_by_filename(workspace: Path, file_name: str) -> Optional[str]:
    """Reuse a media id that already references the same source file name."""
    media_root = workspace / "media"
    if not media_root.is_dir():
        return None
    for entry in media_root.iterdir():
        if not entry.is_dir():
            continue
        meta = _read_json(entry / "metadata.json")
        if meta and meta.get("fileName") == file_name:
            return entry.name
    return None


def _register_short_as_media(workspace: Path, project_id: str, short_path: Path) -> Optional[str]:
    """Copy a generated short into the workspace media library and link it to
    the project. Returns the media id, or None on failure."""
    try:
        file_name = short_path.name
        existing = _find_media_by_filename(workspace, file_name)
        media_id = existing or str(uuid.uuid4())
        media_dir = _media_dir(workspace, media_id)
        media_dir.mkdir(parents=True, exist_ok=True)

        source = media_dir / file_name
        if not source.exists():
            shutil.copy2(short_path, source)

        if not existing:
            meta = {
                "id": media_id,
                "storageType": "workspace",
                "fileName": file_name,
                "fileSize": source.stat().st_size,
                "mimeType": "video/mp4",
                "duration": _probe_duration(source),
                "width": 1080,
                "height": 1920,
                "fps": 30,
                "codec": "avc",
                "bitrate": 0,
                "audioCodec": "aac",
                "audioCodecSupported": True,
                "videoCodecSupported": True,
                "tags": [],
                "createdAt": _now_ms(),
                "updatedAt": _now_ms(),
            }
            _write_json(media_dir / "metadata.json", meta)
            _make_thumbnail(source, media_dir)

        links = _read_json(workspace / "projects" / project_id / "media-links.json")
        if not links:
            links = {"version": _LINKS_VERSION, "mediaIds": []}
        media_ids = links.get("mediaIds") or []
        if not any(m.get("id") == media_id for m in media_ids):
            media_ids.append({"id": media_id, "addedAt": _now_ms()})
        _write_json(workspace / "projects" / project_id / "media-links.json", {
            "version": _LINKS_VERSION,
            "mediaIds": media_ids,
        })
        return media_id
    except (OSError, ValueError):
        return None


# ── transcript (for the editor's Transcript sidebar tab) ─────────────

def _whisper_model_name(model: Optional[str]) -> str:
    """Map a faster-whisper model name to FreeCut's MediaTranscriptModel."""
    if not model:
        return "whisper-base"
    return _WHISPER_MODEL_MAP.get(str(model).lower().strip(), "whisper-base")


def _clip_local_segments(transcript: Dict, start_time: float, end_time: float) -> List[Dict]:
    """Map source-time transcript segments to clip-local time for [start, end].

    Mirrors `_clip_local_segments` in local/clipper.py: only segments that
    overlap the highlight are kept, offset so the clip begins at t=0, and
    clamped to the clip duration. Word dicts are converted to FreeCut's
    `MediaTranscriptWord` shape (`text` key instead of our `word` key).
    """
    out: List[Dict] = []
    clip_duration = max(0.0, float(end_time) - float(start_time))
    for seg in transcript.get("segments", []):
        s = float(seg.get("start", 0.0))
        e = float(seg.get("end", s))
        if e <= start_time or s >= end_time:
            continue
        words = []
        for w in seg.get("words", []):
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
            if we <= start_time or ws >= end_time:
                continue
            words.append({
                "text": str(w.get("word", w.get("text", ""))),
                "start": max(0.0, ws - start_time),
                "end": min(clip_duration, we - start_time),
            })
        out.append({
            "text": seg.get("text", ""),
            "start": max(0.0, s - start_time),
            "end": min(clip_duration, e - start_time),
            "words": words,
        })
    return out


def _transcript_envelope(media_id: str, segments: List[Dict],
                         model: Optional[str], language: Optional[str]) -> Dict:
    """Build FreeCut's AiOutput<'transcript'> envelope for a media id.

    Matches `transcriptFromLegacy`/`writeAiOutput` in vendor/freecut so the
    editor's Transcript tab (via `getTranscript`) picks it straight up. Words
    keep the `text` key the timeline's token builder expects.
    """
    now = _now_ms()
    text = " ".join(seg["text"].strip() for seg in segments if seg.get("text"))
    model_name = _whisper_model_name(model)
    return {
        "schemaVersion": _AI_OUTPUT_SCHEMA_VERSION,
        "kind": "transcript",
        "mediaId": media_id,
        "service": "whisper",
        "model": model_name,
        "params": {"quantization": "q8", "language": language},
        "createdAt": now,
        "updatedAt": now,
        "data": {
            "language": language,
            "quantization": "q8",
            "modelVariant": model_name,
            "text": text,
            "segments": segments,
        },
    }


def _write_media_transcript(workspace: Path, media_id: str, transcript: Optional[Dict],
                            start_time: float, end_time: float,
                            model: Optional[str] = None,
                            language: Optional[str] = None) -> None:
    """Best-effort write of `media/<id>/cache/ai/transcript.json`.

    The editor reads this envelope to populate its Transcript sidebar tab; when
    present (with word timings) it shows the captions instead of offering
    in-browser whisper transcription.
    """
    if not transcript or not transcript.get("segments"):
        return
    try:
        segments = _clip_local_segments(transcript, start_time, end_time)
        if not segments:
            return
        envelope = _transcript_envelope(media_id, segments, model, language)
        path = workspace / "media" / media_id / "cache" / "ai" / "transcript.json"
        _write_json(path, envelope)
    except (OSError, ValueError):
        pass


# ── public API ──────────────────────────────────────────────────────

def _read_clip_window(short_path: Path) -> Optional[Dict]:
    """Read source_start/source_end from the short's .meta.json sidecar."""
    meta = _read_json(short_path.parent / f"{short_path.stem}.meta.json")
    if not meta:
        return None
    start = meta.get("source_start")
    end = meta.get("source_end")
    if start is None or end is None:
        return None
    return {"start": float(start), "end": float(end)}


def sync_freecut_project(workspace, video_id: str, title: Optional[str],
                         short_paths: List[Path],
                         transcript: Optional[Dict] = None,
                         model: Optional[str] = None,
                         language: Optional[str] = None) -> Optional[str]:
    """Create/update the FreeCut project for a source video and register the
    generated shorts as workspace media.

    *workspace* is the FreeCut workspace dir (== the app's output dir).
    *title* names the project (falls back to the video id). *short_paths* are
    the generated short mp4s to import into the media library. *transcript*
    (optional) is the source-level whisper transcript; when provided, each
    short gets a clip-local copy written to `media/<id>/cache/ai/transcript.json`
    so the editor's Transcript tab shows the captions instead of running its
    own in-browser whisper.

    Returns the project id on success, None on failure. Never raises.
    """
    try:
        workspace = Path(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        project_id = _find_project_for_video(workspace, video_id)
        if project_id:
            project = _load_project(workspace, project_id) or _project_object(project_id, title or video_id, video_id)
            project["name"] = title or project.get("name") or video_id
            project["updatedAt"] = _now_ms()
        else:
            project_id = _generate_project_id()
            while _load_project(workspace, project_id) is not None:
                project_id = _generate_project_id()
            project = _project_object(project_id, title or video_id, video_id)

        _write_project(workspace, project)

        registered = []
        for short_path in short_paths:
            media_id = _register_short_as_media(workspace, project_id, Path(short_path))
            if media_id:
                registered.append(media_id)
                window = _read_clip_window(Path(short_path))
                if window:
                    _write_media_transcript(
                        workspace, media_id, transcript,
                        window["start"], window["end"], model=model, language=language,
                    )

        index = _read_index(workspace)
        entries = [e for e in index.get("projects") or [] if e.get("id") != project_id]
        entries.append({"id": project_id, "name": project["name"], "updatedAt": project["updatedAt"]})
        _write_index(workspace, {"projects": entries})

        return project_id
    except Exception:
        return None

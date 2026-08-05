"""Local transcription via faster-whisper.

Reads a local media file and returns the same shape the highlight generator
expects: {duration, segments[start, end, text, words]}. Each segment carries
word-level timestamps (words: [{start, end, word}]) so captions can be
highlighted in sync with the audio.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from ..config import LOCAL_OUTPUT_DIR, LOCAL_WHISPER_DEVICE, LOCAL_WHISPER_MODEL


def _transcript_cache_path(media_path: str) -> Path:
    """Return the .srt cache path for a media file."""
    cache_dir = Path(LOCAL_OUTPUT_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (Path(media_path).stem + ".srt")


def _word_cache_path(media_path: str) -> Path:
    """Return the .json sidecar that stores word-level timestamps."""
    cache_dir = Path(LOCAL_OUTPUT_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / (Path(media_path).stem + ".words.json")


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + (millis / 1000.0)


def _write_srt_cache(media_path: str, transcript: Dict) -> Path:
    cache_path = _transcript_cache_path(media_path)
    lines = []
    for idx, segment in enumerate(transcript.get("segments", []), start=1):
        start = _format_srt_timestamp(float(segment["start"]))
        end = _format_srt_timestamp(float(segment["end"]))
        text = str(segment.get("text", "")).strip().replace("\r", "").replace("\n", " ")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    cache_path.write_text("\n".join(lines), encoding="utf-8")

    # Persist word-level timestamps in a JSON sidecar so captions can be
    # re-rendered in sync with the audio from the cached transcript.
    word_path = _word_cache_path(media_path)
    words_by_segment = []
    for segment in transcript.get("segments", []):
        words_by_segment.append(
            [
                {
                    "start": float(w["start"]),
                    "end": float(w["end"]),
                    "word": str(w.get("word", "")),
                }
                for w in segment.get("words", [])
            ]
        )
    word_path.write_text(
        json.dumps(words_by_segment, ensure_ascii=False),
        encoding="utf-8",
    )
    return cache_path


def _load_srt_cache(cache_path: Path) -> Dict:
    content = cache_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return {"duration": 0.0, "segments": []}

    segments = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
        text = "\n".join(lines[1:]).strip()
        segments.append(
            {
                "start": _parse_srt_timestamp(start_raw),
                "end": _parse_srt_timestamp(end_raw),
                "text": text,
            }
        )

    # Re-attach word-level timestamps from the JSON sidecar if present.
    word_path = _word_cache_path(str(cache_path).replace(".srt", ""))
    if word_path.exists():
        try:
            word_blocks = json.loads(word_path.read_text(encoding="utf-8"))
            for i, segment in enumerate(segments):
                if i < len(word_blocks):
                    segment["words"] = word_blocks[i]
        except (ValueError, OSError):
            pass

    duration = segments[-1]["end"] if segments else 0.0
    return {"duration": duration, "segments": segments}


def _resolve_device() -> str:
    if LOCAL_WHISPER_DEVICE != "auto":
        return LOCAL_WHISPER_DEVICE
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            # Test that CUDA actually works (catches missing cuBLAS/cuDNN libs)
            torch.zeros(1, device="cuda")
            return "cuda"
    except (ImportError, OSError, RuntimeError):
        pass
    return "cpu"


def transcribe_local(media_path: str, language: Optional[str] = None) -> Dict:
    """Run faster-whisper on a local file path, caching the result as .srt."""
    cache_path = _transcript_cache_path(media_path)
    if cache_path.exists():
        source_mtime = os.path.getmtime(media_path)
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime >= source_mtime:
            # Caches created before word-timestamp support have no JSON
            # sidecar — treat them as stale so captions can be synced.
            if not _word_cache_path(media_path).exists():
                print(
                    f"[transcribe/local] cache predates word timestamps, deleting: {cache_path}",
                    flush=True,
                )
                cache_path.unlink(missing_ok=True)
            else:
                print(f"[transcribe/local] reusing cached transcript: {cache_path}", flush=True)
                cached = _load_srt_cache(cache_path)
                # Treat empty cache as invalid (likely from a failed/partial run) — delete and re-transcribe
                if not cached["segments"] or cached["duration"] <= 0.0:
                    print(f"[transcribe/local] cache is empty/invalid, deleting: {cache_path}", flush=True)
                    cache_path.unlink(missing_ok=True)
                else:
                    print(
                        f"[transcribe/local] {len(cached['segments'])} cached segments, "
                        f"{cached['duration']:.0f}s of audio",
                        flush=True,
                    )
                    return cached

    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    device = _resolve_device()
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[transcribe/local] faster-whisper model={LOCAL_WHISPER_MODEL} device={device}", flush=True)

    from ..config import LOCAL_WHISPER_VAD_FILTER, LOCAL_WHISPER_VAD_PARAMETERS
    from ..progress import Progress

    model = WhisperModel(LOCAL_WHISPER_MODEL, device=device, compute_type=compute_type)

    transcribe_kwargs = {
        "audio": media_path,
        "language": language,
        "beam_size": 5,
        "condition_on_previous_text": False,
        "word_timestamps": True,
    }
    if LOCAL_WHISPER_VAD_FILTER:
        transcribe_kwargs["vad_filter"] = True
        transcribe_kwargs["vad_parameters"] = LOCAL_WHISPER_VAD_PARAMETERS
    else:
        transcribe_kwargs["vad_filter"] = False

    segments_iter, info = model.transcribe(**transcribe_kwargs)

    # Probe total duration up-front so the progress bar can show %.
    total_duration = float(getattr(info, "duration", 0.0)) or 0.0
    progress = Progress("Transcribing audio", total=total_duration if total_duration > 0 else None)
    progress.__enter__()

    segments = []
    for s in segments_iter:
        end_t = float(s.end)
        words = []
        for w in getattr(s, "words", None) or []:
            words.append({
                "start": float(w.start),
                "end": float(w.end),
                "word": (w.word or "").strip(),
            })
        segments.append({
            "start": float(s.start),
            "end": end_t,
            "text": (s.text or "").strip(),
            "words": words,
        })
        if total_duration > 0:
            progress.update(end_t)
        # else: spinner thread is updating for us

    duration = total_duration or (segments[-1]["end"] if segments else 0.0)
    progress.finish(f"{len(segments)} segments, {duration:.0f}s of audio")
    transcript = {"duration": duration, "segments": segments}
    cache_path = _write_srt_cache(media_path, transcript)
    print(f"[transcribe/local] wrote cache: {cache_path}", flush=True)
    return transcript

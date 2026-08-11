import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotFound, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import quote

from .models import Clip

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fmt_ts(seconds: float) -> str:
    """Convert float seconds to SRT format: HH:MM:SS,mmm"""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt(path: Path):
    """Return list of dicts: {index, start, end, text} from an SRT file."""
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            int(lines[0])
        except ValueError:
            continue
        m = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            lines[1],
        )
        if not m:
            continue
        start = (
            int(m.group(1)) * 3600
            + int(m.group(2)) * 60
            + int(m.group(3))
            + int(m.group(4)) / 1000
        )
        end = (
            int(m.group(5)) * 3600
            + int(m.group(6)) * 60
            + int(m.group(7))
            + int(m.group(8)) / 1000
        )
        segments.append(
            {
                "index": int(lines[0]),
                "start": start,
                "end": end,
                "text": " ".join(lines[2:]),
            }
        )
    return segments


def _ffprobe(path: Path, entry: str = "format=duration"):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entry, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return r.stdout.strip() if r.returncode == 0 else "0"


def _get_video_status(video_id):
    out = Path(settings.OUTPUT_DIR)
    mp4 = out / f"source_{video_id}.mp4"
    srt = out / f"source_{video_id}.srt"

    status = []
    if mp4.exists():
        status.append(("downloaded", "Done"))
    else:
        return status  # nothing else possible

    if srt.exists():
        segs = _parse_srt(srt)
        status.append(("transcribed", f"{len(segs)} segments"))

    clips = Clip.objects.filter(video_id=video_id).count()
    if clips:
        status.append(("clips", f"{clips} clip{'s' if clips > 1 else ''}"))

    shorts = list(out.glob(f"short_{video_id}_*.mp4"))
    if shorts:
        status.append(("generated", f"{len(shorts)} short{'s' if len(shorts) > 1 else ''}"))

    return status


def _get_source_videos():
    out_dir = Path(settings.OUTPUT_DIR)
    videos = []
    for f in sorted(out_dir.glob("source_*.mp4")):
        vid = f.stem.replace("source_", "", 1)
        dur = _ffprobe(f)
        srt_path = out_dir / f"{f.stem}.srt"
        srt_segments = _parse_srt(srt_path) if srt_path.exists() else []
        videos.append(
            {
                "id": vid,
                "filename": f.name,
                "duration": float(dur) if dur else 0,
                "srt_count": len(srt_segments),
                "status_chain": _get_video_status(vid),
            }
        )
    return videos


# ── Views ──────────────────────────────────────────────────────────

def _home_context(extra=None):
    ctx = {
        "videos": _get_source_videos(),
        "exports": _collect_exports(),
    }
    if extra:
        ctx.update(extra)
    return ctx


def home(request):
    return render(request, "webui/home.html", _home_context())


@csrf_exempt
def download(request):
    if request.method == "POST":
        url = request.POST.get("url", "").strip()
        if not url:
            return redirect("home")
        try:
            from shorts_generator.local.downloader import download_youtube_local
            download_youtube_local(url, fmt="720")
        except Exception as e:
            return render(request, "webui/home.html", _home_context({
                "error": f"Download failed: {e}",
            }))
    return redirect("home")


@csrf_exempt
def transcribe(request, video_id):
    out = Path(settings.OUTPUT_DIR)
    source = out / f"source_{video_id}.mp4"
    if not source.exists():
        return redirect("home")
    try:
        from shorts_generator.local.transcriber import transcribe_local
        transcribe_local(str(source))
    except Exception as e:
        return render(request, "webui/home.html", _home_context({
            "error": f"Transcribe failed: {e}",
        }))
    return redirect("home")


def clip_editor(request, video_id):
    out_dir = Path(settings.OUTPUT_DIR)
    source_path = out_dir / f"source_{video_id}.mp4"
    srt_path = out_dir / f"source_{video_id}.srt"

    if not source_path.exists():
        return redirect("home")

    segments = _parse_srt(srt_path) if srt_path.exists() else []
    for seg in segments:
        seg["ts"] = _fmt_ts(seg["start"])
        seg["te"] = _fmt_ts(seg["end"])

    clips = list(Clip.objects.filter(video_id=video_id))
    for c in clips:
        c.start_ts = _fmt_ts(c.start_time)
        c.end_ts = _fmt_ts(c.end_time)
        c.duration_ts = _fmt_ts(c.end_time - c.start_time)

    duration = float(_ffprobe(source_path)) or 0
    generated_shorts = sorted(out_dir.glob(f"short_{video_id}_*.mp4"))
    msg = request.GET.get("msg", "")

    return render(request, "webui/clip_editor.html", {
        "video_id": video_id,
        "filename": source_path.name,
        "duration": duration,
        "segments": segments,
        "clips": clips,
        "generated_shorts": generated_shorts,
        "msg": msg,
    })


@csrf_exempt
@transaction.atomic
def add_clip(request, video_id):
    if request.method == "POST":
        start = float(request.POST["start"])
        end = float(request.POST["end"])
        if end > start:
            Clip.objects.create(video_id=video_id, start_time=start, end_time=end)
    return HttpResponseRedirect(reverse("clip_editor", kwargs={"video_id": video_id}))


@csrf_exempt
@transaction.atomic
def delete_clip(request, video_id, clip_id):
    if request.method == "POST":
        Clip.objects.filter(id=clip_id, video_id=video_id).delete()
    return HttpResponseRedirect(reverse("clip_editor", kwargs={"video_id": video_id}))


@csrf_exempt
def generate(request, video_id):
    clips = Clip.objects.filter(video_id=video_id)
    if not clips.exists():
        return redirect("clip_editor", video_id=video_id)

    template = request.POST.get("template", "stage_solo_speaker")

    out_dir = Path(settings.OUTPUT_DIR)
    source_path = out_dir / f"source_{video_id}.mp4"

    generated = []
    errors = []
    for i, clip in enumerate(clips):
        out_path = out_dir / f"short_{video_id}_c{clip.id:04d}.mp4"
        try:
            from shorts_generator.local.clipper import crop_clip_local
            # Captions are left out here on purpose: they are added as layers in
            # the editor and baked in at export time, so nothing is double-burned.
            crop_clip_local(
                str(source_path),
                clip.start_time,
                clip.end_time,
                str(out_path),
                template=template,
            )
            generated.append(str(out_path.name))
            # Record the source window so captions still map even if the Clip
            # row is later deleted/recreated.
            meta = out_dir / f"{out_path.stem}.meta.json"
            meta.write_text(json.dumps({
                "video_id": video_id,
                "clip_id": clip.id,
                "source_start": clip.start_time,
                "source_end": clip.end_time,
            }), encoding="utf-8")
        except Exception as e:
            errors.append(f"clip {i + 1} ({clip.start_time:.1f}-{clip.end_time:.1f}s): {e}")

    msg = f"Generated {len(generated)} short{'s' if len(generated) != 1 else ''} (template: {template})"
    if errors:
        details = "; ".join(errors)
        msg += f", {len(errors)} failed: {details}"

    # Hand off to the FreeCut editor with the generated short on disk.
    if generated:
        target = reverse("editor_shell", kwargs={"video_id": video_id})
    else:
        target = reverse("clip_editor", kwargs={"video_id": video_id})
    return HttpResponseRedirect(f"{target}?msg={quote(msg)}")


@csrf_exempt
def auto_generate(request):
    """Full auto-pipeline ported from the CLI into the web UI.

    POST: url, num_clips, format, language, min_clip_seconds,
          max_clip_seconds, template.

    Runs download (if needed) -> transcribe (if needed) -> LLM highlight
    ranking -> creates Clip rows -> crops each to 9:16 (caption-free, so
    captions land on the editor timeline instead of being baked in) ->
    redirects into the FreeCut editor.
    """
    if request.method != "POST":
        return redirect("home")

    url = request.POST.get("url", "").strip()
    if not url:
        return redirect("home")
    num_clips = max(1, min(20, int(request.POST.get("num_clips", 10) or 10)))
    fmt = request.POST.get("format", "720") or "720"
    language = (request.POST.get("language", "") or "").strip() or None
    min_sec = max(5, int(request.POST.get("min_clip_seconds", 30) or 30))
    max_sec = max(min_sec, int(request.POST.get("max_clip_seconds", 60) or 60))
    template = request.POST.get("template", "stage_solo_speaker")

    out_dir = Path(settings.OUTPUT_DIR)
    try:
        from shorts_generator.local.downloader import download_youtube_local
        from shorts_generator.local.llm import call_local_llm
        from shorts_generator.local.transcriber import transcribe_local
        from shorts_generator.highlights import get_highlights

        source_path = Path(download_youtube_local(url, fmt=fmt))
        video_id = source_path.stem.replace("source_", "", 1)
        if not str(source_path).startswith(str(out_dir)):
            target = out_dir / f"source_{video_id}.mp4"
            if not target.exists() or target.stat().st_size != source_path.stat().st_size:
                import shutil
                shutil.copy2(source_path, target)
            source_path = target

        transcript = transcribe_local(str(source_path), language=language)
        if not transcript.get("segments"):
            raise RuntimeError("Whisper produced no segments.")

        result = get_highlights(
            transcript,
            num_clips=num_clips,
            llm_fn=call_local_llm,
            min_clip_seconds=min_sec,
            max_clip_seconds=max_sec,
        )
        highlights = sorted(
            result.get("highlights", []),
            key=lambda h: int(h.get("score", 0) or 0),
            reverse=True,
        )[:num_clips]
        if not highlights:
            raise RuntimeError("Highlight generator returned zero clips.")

        from shorts_generator.local.clipper import crop_clip_local

        # Reuse existing Clip rows that already cover the same windows, so
        # re-running doesn't duplicate DB rows.
        existing = list(Clip.objects.filter(video_id=video_id))
        generated = []
        for h in highlights:
            s = float(h["start_time"])
            e = float(h["end_time"])
            clip = next(
                (c for c in existing if abs(c.start_time - s) < 0.5 and abs(c.end_time - e) < 0.5),
                None,
            )
            if clip is None:
                clip = Clip.objects.create(video_id=video_id, start_time=s, end_time=e)
                existing.append(clip)
            out_path = out_dir / f"short_{video_id}_c{clip.id:04d}.mp4"
            try:
                crop_clip_local(str(source_path), s, e, str(out_path), template=template)
                meta = out_dir / f"{out_path.stem}.meta.json"
                meta.write_text(json.dumps({
                    "video_id": video_id,
                    "clip_id": clip.id,
                    "source_start": s,
                    "source_end": e,
                }), encoding="utf-8")
                generated.append(str(out_path.name))
            except Exception as exc:
                pass  # keep going; failed clip simply isn't listed

        if not generated:
            raise RuntimeError("All highlight clips failed to render.")
    except Exception as exc:
        return render(request, "webui/home.html", _home_context({
            "error": f"Auto-generate failed: {exc}",
        }))

    msg = (f"Auto-generated {len(generated)} short{'s' if len(generated) != 1 else ''} "
           f"({template}) from {len(highlights)} highlights")
    target = reverse("editor_shell", kwargs={"video_id": video_id})
    return HttpResponseRedirect(f"{target}?msg={quote(msg)}")


def _file_response(request, path: Path, content_type: str) -> HttpResponse:
    """Serve a file with byte-range support (206/416 handled correctly)."""
    size = path.stat().st_size
    range_header = request.META.get("HTTP_RANGE", "")

    if range_header:
        m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if m:
            start_s, end_s = m.groups()
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            if start >= size:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{size}"
                return response
            end = min(end, size - 1)
            length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start)
                chunk = f.read(length)
            response = HttpResponse(chunk, status=206, content_type=content_type)
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
            response["Content-Length"] = str(length)
            response["Accept-Ranges"] = "bytes"
            return response

    response = FileResponse(open(path, "rb"), content_type=content_type)
    response["Content-Length"] = str(size)
    response["Accept-Ranges"] = "bytes"
    return response


def serve_output(request, filename):
    path = Path(settings.OUTPUT_DIR) / filename
    if not path.exists() or not path.is_file():
        raise Http404()
    return _file_response(request, path, _mime_for(path.name))


def download_transcript(request, video_id):
    srt_path = Path(settings.OUTPUT_DIR) / f"source_{video_id}.srt"
    if not srt_path.exists():
        raise Http404()
    response = FileResponse(
        open(srt_path, "rb"),
        content_type="text/plain",
    )
    response["Content-Disposition"] = f'attachment; filename="source_{video_id}.srt"'
    return response


def _mime_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext in (".webm",):
        return "video/webm"
    if ext in (".mp3",):
        return "audio/mpeg"
    if ext in (".wav",):
        return "audio/wav"
    if ext in (".m4a", ".aac"):
        return "audio/mp4"
    if ext in (".ogg",):
        return "audio/ogg"
    if ext in (".srt",):
        return "text/plain"
    return "application/octet-stream"


# ── FreeCut browser editor ──────────────────────────────────────────
# FreeCut (vendor/freecut) is the only video editor now. It is a client-side
# WebGPU/WebCodecs app that needs cross-origin isolation (SharedArrayBuffer)
# and plain static hosting with byte-range support. The workspace is the
# output dir, so sources, transcripts, assets and editor exports all live in
# one place; FreeCut writes exports to projects/<id>/exports/.

_EDITOR_MIME = {
    ext: ct
    for ext, ct in [
        (".html", "text/html; charset=utf-8"),
        (".js", "text/javascript; charset=utf-8"),
        (".mjs", "text/javascript; charset=utf-8"),
        (".css", "text/css; charset=utf-8"),
        (".json", "application/json"),
        (".map", "application/json"),
        (".webmanifest", "application/manifest+json"),
        (".svg", "image/svg+xml"),
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".avif", "image/avif"),
        (".ico", "image/x-icon"),
        (".wasm", "application/wasm"),
        (".woff", "font/woff"),
        (".woff2", "font/woff2"),
        (".ttf", "font/ttf"),
        (".otf", "font/otf"),
        (".onnx", "application/octet-stream"),
        (".bin", "application/octet-stream"),
        (".mp3", "audio/mpeg"),
        (".wav", "audio/wav"),
    ]
}


def _isolated_headers(response):
    """Cross-origin-isolate a response so FreeCut's SharedArrayBuffer works."""
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    response["Cross-Origin-Embedder-Policy"] = "require-corp"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


def _collect_exports():
    """Newest-first mp4s that FreeCut wrote into the workspace exports dir."""
    ws = Path(settings.FREECUT_WORKSPACE)
    exports = []
    if ws.is_dir():
        for p in ws.glob("projects/*/exports/*.mp4"):
            try:
                st = p.stat()
            except OSError:
                continue
            exports.append({
                "name": p.name,
                "path": str(p.relative_to(ws)).replace("\\", "/"),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    exports.sort(key=lambda e: e["mtime"], reverse=True)
    return exports


def freecut_exports(request):
    return JsonResponse({"exports": _collect_exports()})


@csrf_exempt
def editor_app(request, path=""):
    """Serve the vendored FreeCut build under /editor/.

    Maps every URL under /editor/ onto the committed dist/ tree (assets,
    wasm, models, SW, SPA fallback for client-side routes). All responses
    are cross-origin-isolated so the WebCodecs renderer can use
    SharedArrayBuffer.
    """
    dist = Path(settings.FREECUT_DIST)
    if not dist.is_dir():
        return _isolated_headers(HttpResponse(
            "FreeCut editor build is missing. Rebuild it with "
            "`npm ci && npm run build` in vendor/freecut.",
            status=500,
        ))

    rel = (path or "index.html").replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/"):
        return _isolated_headers(HttpResponseNotFound("not found"))

    target = (dist / rel).resolve()
    if not str(target).startswith(str(dist.resolve())):
        return _isolated_headers(HttpResponseNotFound("not found"))

    if target.is_dir():
        target = target / "index.html"
    if target.is_file():
        content_type = _EDITOR_MIME.get(target.suffix.lower(), "application/octet-stream")
        return _isolated_headers(_file_response(request, target, content_type))

    # SPA fallback: extensionless client-side routes resolve to index.html.
    if not target.suffix:
        index_html = dist / "index.html"
        if index_html.is_file():
            return _isolated_headers(_file_response(
                request, index_html, _EDITOR_MIME[".html"]))
    return _isolated_headers(HttpResponseNotFound("not found"))


def editor_shell(request, video_id):
    """Full page embedding the FreeCut editor for one source video."""
    out_dir = Path(settings.OUTPUT_DIR)
    source_path = out_dir / f"source_{video_id}.mp4"
    if not source_path.exists():
        return redirect("home")

    source_url = reverse("serve_output", args=[source_path.name])
    return _isolated_headers(render(request, "webui/editor_shell.html", {
        "video_id": video_id,
        "filename": source_path.name,
        "duration": float(_ffprobe(source_path)) or 0,
        "source_url": source_url,
        "has_srt": (out_dir / f"source_{video_id}.srt").exists(),
        "srt_url": reverse("download_transcript", args=[video_id]),
        "workspace": str(Path(settings.FREECUT_WORKSPACE)),
        "editor_url": reverse("editor_app"),
        "exports": _collect_exports(),
    }))


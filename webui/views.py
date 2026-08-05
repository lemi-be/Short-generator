import json
import re
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

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

def home(request):
    return render(request, "webui/home.html", {"videos": _get_source_videos()})


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
            return render(request, "webui/home.html", {
                "videos": _get_source_videos(),
                "error": f"Download failed: {e}",
            })
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
        return render(request, "webui/home.html", {
            "videos": _get_source_videos(),
            "error": f"Transcribe failed: {e}",
        })
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
    srt_path = out_dir / f"source_{video_id}.srt"

    transcript = None
    if srt_path.exists():
        from shorts_generator.local.transcriber import _load_srt_cache
        transcript = _load_srt_cache(srt_path)

    generated = []
    errors = []
    for i, clip in enumerate(clips):
        out_path = out_dir / f"short_{video_id}_c{clip.id:04d}.mp4"
        try:
            from shorts_generator.local.clipper import _clip_local_segments, crop_clip_local
            segments = (
                _clip_local_segments(transcript, clip.start_time, clip.end_time)
                if transcript
                else None
            )
            crop_clip_local(
                str(source_path),
                clip.start_time,
                clip.end_time,
                str(out_path),
                template=template,
                segments=segments,
            )
            generated.append(str(out_path.name))
        except Exception as e:
            errors.append(f"clip {i + 1} ({clip.start_time:.1f}-{clip.end_time:.1f}s): {e}")

    msg = f"Generated {len(generated)} short{'s' if len(generated) != 1 else ''} (template: {template})"
    if errors:
        details = "; ".join(errors)
        msg += f", {len(errors)} failed: {details}"
    return HttpResponseRedirect(f"{reverse('clip_editor', kwargs={'video_id': video_id})}?msg={msg}")


def serve_output(request, filename):
    path = Path(settings.OUTPUT_DIR) / filename
    if not path.exists() or not path.is_file():
        raise Http404()

    size = path.stat().st_size
    content_type = _mime_for(path.name)
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


def _ffmpeg_quote(text: str) -> str:
    """Escape text for use as a single-quoted filtergraph value.

    Inside filtergraph single quotes, a literal quote is escaped by closing,
    writing \\', and reopening. '%' must be escaped because drawtext expands
    printf-style tokens. Backslashes are passed through untouched.
    """
    return "'" + text.replace("'", "'\\''").replace("%", "\\%") + "'"


def _fontfile_value(bold: bool = True) -> str:
    """Return a filtergraph-escaped Windows font path (single backslash before ':').

    drawtext requires the drive colon to be escaped (\:) but the backslash must
    stay a single character, so this is built directly instead of via _ffmpeg_quote.
    """
    return "'C\\:/Windows/Fonts/arialbd.ttf'" if bold else "'C\\:/Windows/Fonts/arial.ttf'"


def _hex_to_alpha(hex_color: str, alpha: float) -> str:
    """Convert '#rrggbb' + alpha 0..1 into ffmpeg's '0xrrggbbaa' boxcolor form."""
    hex_color = (hex_color or "#000000").lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) < 6:
        hex_color = (hex_color + "000000")[:6]
    a = int(max(0.0, min(1.0, float(alpha))) * 255)
    return f"0x{hex_color}{a:02X}"


def _video_dims(path: Path):
    """Return (width, height) of the first video stream, defaulting to 1080x1920."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except (ValueError, IndexError):
        return 1080, 1920


def _render_with_layers(
    src: Path,
    start: float,
    end: float,
    dst: Path,
    text_layers: list,
    audio_layers: list,
    out_dir: Path,
    logo: dict = None,
    cuts: list = None,
    source_volume: float = 1.0,
    ducking: bool = False,
) -> None:
    """Refine src to [start,end]: text hooks, watermark overlay, cut ranges,
    background-audio mixing with optional ducking, and source-volume control.

    All timestamps (text layers, cuts) are on the FULL-CLIP time axis and are
    shifted by *start* internally. The video filtergraph runs text + logo
    BEFORE the cut filter, so any overlay that overlaps a cut region is removed
    along with the footage — matching what the user sees on the range bar.

    text_layers: [{text, start, end, x, y, size, color, bgColor, bgAlpha,
                   bold, stroke, strokeColor, strokeAlpha, uppercase, animation}]
                  x/y are center-anchor percentages (0-100).
    audio_layers: [{file, start, volume}]  (file = filename under OUTPUT_DIR)
    logo: {file, x, y, scale, opacity}  (x/y = top-left percentages)
    cuts: [[start, end], ...]           (full-clip time, non-overlapping)
    """
    duration = end - start

    extra_inputs = []  # every additional -i (audio files, then logo images)

    def _add_input(path: Path) -> int:
        extra_inputs.append(str(path))
        return len(extra_inputs)  # 1-based index (0 is the source)

    fc_parts = []

    # ================= Video chain =================
    cur = "[0:v]"  # cursor label; every step appends an output label
    has_vfilter = False
    vstep_n = 0

    def _video_step(chain: str) -> None:
        nonlocal cur, has_vfilter, vstep_n
        lbl = f"[vt{vstep_n}]"
        vstep_n += 1
        fc_parts.append(cur + chain + lbl)
        cur = lbl
        has_vfilter = True

    text_draws = []
    for layer in text_layers:
        t0 = max(0.0, float(layer.get("start", 0)) - start)
        t1 = min(duration, float(layer.get("end", duration)) - start)
        if t1 <= t0:
            continue
        text = str(layer.get("text", "")).strip()
        if not text:
            continue
        if layer.get("uppercase"):
            text = text.upper()
        size = int(float(layer.get("size", 48) or 48))
        color = str(layer.get("color", "white") or "white")
        bold = bool(layer.get("bold"))
        font = _fontfile_value(bold)
        box_color = _hex_to_alpha(
            str(layer.get("bgColor", "#000000") or "#000000"),
            float(layer.get("bgAlpha", 0.45) or 0.45),
        )
        x = float(layer.get("x", 50) or 50)
        y = float(layer.get("y", 12) or 12)
        pad = int(float(layer.get("pad", 16) or 16))
        x_expr = f"w*{x / 100:.6f}-text_w/2"
        y_expr = f"h*{y / 100:.6f}-th/2"
        d = (
            f"drawtext=fontfile={font}"
            f":text={_ffmpeg_quote(text)}"
            f":fontsize={size}:fontcolor={_ffmpeg_quote(color)}"
            f":box=1:boxcolor={_ffmpeg_quote(box_color)}:boxborderw={pad}"
        )
        stroke = int(float(layer.get("stroke", 0) or 0))
        if stroke > 0:
            stroke_color = _hex_to_alpha(
                str(layer.get("strokeColor", "#000000") or "#000000"),
                float(layer.get("strokeAlpha", 0.9) or 0.9),
            )
            d += f":borderw={stroke}:bordercolor={_ffmpeg_quote(stroke_color)}"
        d += f":x={_ffmpeg_quote(x_expr)}:y={_ffmpeg_quote(y_expr)}"
        d += f":enable={_ffmpeg_quote(f'between(t,{t0:.3f},{t1:.3f})')}"
        if str(layer.get("animation", "")) == "pop":
            d += f":alpha={_ffmpeg_quote(f'clip((t-{t0:.3f})/0.3,0,1)')}"
        text_draws.append(d)

    if text_draws:
        _video_step(",".join(text_draws))

    if logo and logo.get("file"):
        logo_path = out_dir / str(logo["file"])
        if logo_path.exists():
            canvas_w, canvas_h = _video_dims(src)
            scale = float(logo.get("scale", 0.12) or 0.12)
            opacity = float(logo.get("opacity", 1.0) or 1.0)
            px_w = max(4, int(canvas_w * scale))
            x = int(canvas_w * (float(logo.get("x", 3) or 3) / 100.0))
            y = int(canvas_h * (float(logo.get("y", 3) or 3) / 100.0))
            idx = _add_input(logo_path)
            if opacity >= 1.0:
                fc_parts.append(f"[{idx}:v]scale={px_w}:-1:flags=lanczos[lg]")
            else:
                fc_parts.append(
                    f"[{idx}:v]scale={px_w}:-1:flags=lanczos,format=rgba,"
                    f"colorchannelmixer=aa={opacity:.3f}[lg]"
                )
            _video_step(f"[lg]overlay={x}:{y}")

    # Cut ranges compact the timeline (video + audio) AFTER overlays.
    # Cuts arrive on the full-clip axis; shift to draft-local time (t=0 at
    # trim start) to match the post-`-ss` filter timeline.
    local_cuts = []
    if cuts:
        for s, e in cuts:
            ls = max(0.0, s - start)
            le = min(duration, e - start)
            if le > ls + 0.05:
                local_cuts.append((ls, le))

    if local_cuts:
        cut_expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in local_cuts)
        _video_step(f"select='not({cut_expr})',setpts=N/FRAME_RATE/TB")

    # The final output must be labelled [vout] for -map.
    if has_vfilter and cur != "[vout]":
        fc_parts.append(f"{cur}null[vout]")

    # ================= Audio chain =================
    bgm_labels = []
    for i, layer in enumerate(audio_layers):
        audio_file = str(layer.get("file", ""))
        if not audio_file:
            continue
        audio_path = out_dir / audio_file
        if not audio_path.exists():
            continue
        lstart = float(layer.get("start", 0))
        volume = float(layer.get("volume", 1.0) or 1.0)
        delay_ms = int(max(0, lstart - start) * 1000)
        idx = _add_input(audio_path)
        lbl = f"abgm{i}"
        bgm_labels.append(lbl)
        fc_parts.append(
            f"[{idx}:a]volume={volume:.3f},adelay={delay_ms}:all=1,apad[{lbl}]"
        )

    needs_audio = bool(bgm_labels) or bool(local_cuts) or abs(source_volume - 1.0) > 1e-6
    if needs_audio:
        src_chain = f"[0:a]atrim=0:{duration:.3f}"
        if abs(source_volume - 1.0) > 1e-6:
            src_chain += f",volume={source_volume:.3f}"
        src_chain += ",asetpts=PTS-STARTPTS[a_src]"
        fc_parts.append(src_chain)

        if bgm_labels:
            mixed_labels = []
            if ducking:
                for lbl in bgm_labels:
                    fc_parts.append(
                        f"[{lbl}][a_src]sidechaincompress=threshold=0.03:ratio=6:"
                        f"attack=20:release=250[{lbl}_d]"
                    )
                    mixed_labels.append(f"[{lbl}_d]")
            else:
                mixed_labels = [f"[{lbl}]" for lbl in bgm_labels]
            fc_parts.append(
                f"[a_src]{''.join(mixed_labels)}amix=inputs={1 + len(bgm_labels)}:"
                f"duration=first:dropout_transition=2[amix]"
            )
            final_audio = "[amix]"
        else:
            final_audio = "[a_src]"

        if local_cuts:
            cut_expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in local_cuts)
            fc_parts.append(
                f"{final_audio}aselect='not({cut_expr})',asetpts=N/SR/TB[aout]"
            )
            final_audio = "[aout]"
        else:
            fc_parts.append(f"{final_audio}anull[aout]")
            final_audio = "[aout]"

    has_afilter = needs_audio

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    # -ss/-t MUST precede -i so they act as INPUT options. As output options
    # they do not reliably limit a filter_complex-mapped output duration.
    cmd += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    for extra in extra_inputs:
        cmd += ["-i", str(extra)]

    if fc_parts:
        cmd += ["-filter_complex", ";".join(fc_parts)]
    cmd += ["-map", "[vout]" if has_vfilter else "0:v"]
    cmd += ["-map", "[aout]" if has_afilter else "0:a"]
    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


@csrf_exempt
def upload_audio(request, video_id):
    """Store an uploaded audio file under output/audio_layers/ for use as a layer."""
    if request.method != "POST" or not request.FILES.get("file"):
        return JsonResponse({"error": "no file"}, status=400)

    f = request.FILES["file"]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)
    sub = Path(settings.OUTPUT_DIR) / "audio_layers"
    sub.mkdir(parents=True, exist_ok=True)
    safe = f"{int(time.time())}_{name}"
    dest = sub / safe
    with open(dest, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    return JsonResponse({"file": f"audio_layers/{safe}", "url": reverse("serve_output", args=[f"audio_layers/{safe}"])})


@csrf_exempt
def upload_logo(request, video_id):
    """Store an uploaded logo/watermark image under output/logos/."""
    if request.method != "POST" or not request.FILES.get("file"):
        return JsonResponse({"error": "no file"}, status=400)

    f = request.FILES["file"]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)
    sub = Path(settings.OUTPUT_DIR) / "logos"
    sub.mkdir(parents=True, exist_ok=True)
    safe = f"{int(time.time())}_{name}"
    dest = sub / safe
    with open(dest, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    return JsonResponse({"file": f"logos/{safe}", "url": reverse("serve_output", args=[f"logos/{safe}"])})


@csrf_exempt
def trim_short(request, video_id, filename):
    """Trimmer page for a generated short + POST handler that re-cuts it."""
    out_dir = Path(settings.OUTPUT_DIR)
    src = out_dir / filename
    if not src.exists():
        raise Http404()

    if request.method == "POST":
        duration = float(_ffprobe(src)) or 0
        start = max(0.0, min(float(request.POST.get("start", 0) or 0), duration))
        end = max(start, min(float(request.POST.get("end", 0) or 0), duration))
        if end - start < 0.1:
            return HttpResponseRedirect(reverse("clip_editor", kwargs={"video_id": video_id}) + "?msg=Trim failed: end must be after start")

        text_layers = []
        audio_layers = []
        logo = None
        cuts = []
        ducking = False
        source_volume = 1.0
        raw = request.POST.get("layers", "")
        if raw:
            try:
                layers = json.loads(raw)
                text_layers = layers.get("text", []) or []
                audio_layers = layers.get("audio", []) or []
                logo = layers.get("logo") or None
                ducking = bool(layers.get("ducking", False))
                source_volume = float(layers.get("source_volume", 1.0) or 1.0)
                for c in layers.get("cuts", []) or []:
                    try:
                        s, e = float(c[0]), float(c[1])
                    except (ValueError, TypeError, IndexError):
                        continue
                    if e > s + 0.05:
                        cuts.append([s, e])
            except (ValueError, AttributeError, TypeError):
                pass

        # Normalise cuts: clamp, sort, merge overlaps (all on the full-clip axis).
        cuts.sort()
        merged_cuts = []
        for s, e in cuts:
            s = max(0.0, min(s, duration))
            e = max(0.0, min(e, duration))
            if e <= s:
                continue
            if merged_cuts and s < merged_cuts[-1][1]:
                merged_cuts[-1][1] = max(merged_cuts[-1][1], e)
            else:
                merged_cuts.append([s, e])

        stem = src.stem
        trimmed = out_dir / f"{stem}_trimmed.mp4"
        n = 1
        while trimmed.exists():
            trimmed = out_dir / f"{stem}_trimmed_{n}.mp4"
            n += 1
        _render_with_layers(
            src, start, end, trimmed,
            text_layers, audio_layers, out_dir,
            logo=logo, cuts=merged_cuts,
            source_volume=source_volume, ducking=ducking,
        )
        bits = []
        if text_layers:
            bits.append(f"{len(text_layers)} text")
        if logo:
            bits.append("watermark")
        if audio_layers:
            bits.append(f"{len(audio_layers)} audio")
        if merged_cuts:
            bits.append(f"{len(merged_cuts)} cut{'s' if len(merged_cuts) > 1 else ''}")
        extra = f" ({', '.join(bits)})" if bits else ""
        msg = f"Rendered {filename} {start:.1f}s-{end:.1f}s{extra} -> {trimmed.name}"
        return HttpResponseRedirect(reverse("clip_editor", kwargs={"video_id": video_id}) + f"?msg={msg}")

    duration = float(_ffprobe(src)) or 0
    return render(request, "webui/trim_short.html", {
        "video_id": video_id,
        "filename": filename,
        "duration": duration,
    })

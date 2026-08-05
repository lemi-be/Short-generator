import json
import os
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


def _fontfile_value(bold: bool = True, file: str = "") -> str:
    """Return a filtergraph-escaped Windows font path (single backslash before ':').

    drawtext requires the drive colon to be escaped (\:) but the backslash must
    stay a single character, so this is built directly instead of via _ffmpeg_quote.
    If *file* is an absolute path it is used as-is; if it is just a filename it
    is resolved inside C:/Windows/Fonts.
    """
    if file:
        if ":" in file and not file.startswith("C:"):
            # Allow a full absolute path to be handed straight to drawtext.
            return _ffmpeg_quote(file)
        return f"'C\\:/Windows/Fonts/{file.replace('C:/Windows/Fonts/', '').replace('\\\\', '/')}'"
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


def _clampf(value, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _voice_enhance_chain(enhance: float) -> str:
    """ffmpeg chain (no leading comma) for voice polish, 0..1 intensity."""
    nr = 10 + 15 * enhance
    gain = 0.5 + 5.5 * enhance
    compand = (
        "compand=attacks=0.1:decays=0.2:"
        "points=-80/-80|-45/-25|-27/-20|0/-6|20/-2|40/0"
        ":soft-knee=6:gain=" + f"{gain:.2f}"
    )
    return f"highpass=f=80,afftdn=nr={nr:.1f}:nf=-40,{compand},alimiter=limit=0.95"


def _build_filter_chain(filters: list) -> str:
    """Video color / attention filters (vignette, spotlight, grade, ...)."""
    parts = []
    for f in filters or []:
        kind = str(f.get("kind", ""))
        i = _clampf(f.get("intensity", 50))
        if kind == "vignette":
            parts.append(f"vignette=angle='PI/4*{i:.3f}'")
        elif kind == "contrast":
            parts.append(
                f"eq=contrast={1 + 0.45 * i:.3f}:saturation={1 + 0.35 * i:.3f}"
                f":brightness={0.03 * i:.3f}"
            )
        elif kind == "warm":
            parts.append(
                f"colorbalance=rs={0.14 * i:.3f}:gs={0.05 * i:.3f}:bs={-0.12 * i:.3f}:"
                f"rm={0.06 * i:.3f}:gm={0.02 * i:.3f}:bm={-0.05 * i:.3f}:"
                f"rh={0.03 * i:.3f}:gh={0.01 * i:.3f}:bh={-0.03 * i:.3f}"
            )
        elif kind == "cool":
            parts.append(
                f"colorbalance=rs={-0.12 * i:.3f}:gs={-0.03 * i:.3f}:bs={0.14 * i:.3f}:"
                f"rm={-0.05 * i:.3f}:gm={-0.01 * i:.3f}:bm={0.06 * i:.3f}:"
                f"rh={-0.03 * i:.3f}:gh={-0.01 * i:.3f}:bh={0.03 * i:.3f}"
            )
        elif kind == "crisp":
            parts.append(f"unsharp=5:5:{0.2 + 0.8 * i:.3f}:5:5:0")
        elif kind == "neon":
            parts.append(
                f"curves=all='0/0 0.5/{0.55 + 0.25 * i:.3f} 1/1',"
                f"unsharp=5:5:{0.3 + 0.7 * i:.3f}:5:5:0"
            )
        elif kind == "spotlight":
            parts.append(
                f"vignette=angle='PI/4*(0.5+0.5*{i:.3f})',"
                f"eq=contrast={1 + 0.25 * i:.3f}:brightness={0.02 * i:.3f}"
            )
        elif kind == "desat":
            parts.append(f"hue=s={1 - i:.3f}")
    return ",".join(parts)


def _probe_audio_info(path: Path):
    """Return (duration_s, sample_rate) of the first audio stream."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=duration,sample_rate", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        dur_s, sr_s = r.stdout.strip().split(",")
        return float(dur_s or 0), int(sr_s or 44100)
    except (ValueError, IndexError):
        return 0.0, 44100


def _render_layers(
    src: Path,
    start: float,
    end: float,
    dst: Path,
    layers: dict,
    out_dir: Path,
) -> None:
    """Render src[start:end] with a full layer stack into dst.

    Layer timestamps live on the SHORT timeline (t=0 = short start) and are
    shifted by *start* internally. Cuts compact the timeline AFTER overlays,
    so overlay times always match the range UI. Builds one ffmpeg
    filter_complex: text -> logo -> stock PiP -> cuts -> filters -> effects,
    and voice -> bgm(duck) -> sfx for audio.
    """
    duration = end - start
    text_layers = (layers.get("text") or []) + (layers.get("captions") or [])
    stock_layers = layers.get("stock") or []
    sfx_layers = layers.get("sfx") or []
    bgm_layers = layers.get("bgm") or []
    logo = layers.get("logo") or None
    audioFx = layers.get("audioFx") or {}
    enhance = _clampf(audioFx.get("enhance", 0))
    ducking = _clampf(audioFx.get("ducking", 0))
    filters = layers.get("filters") or []
    effects = layers.get("effects") or {}
    source_volume = float(layers.get("source_volume", 1.0) or 1.0)
    cuts = layers.get("cuts") or []

    extra_inputs = []  # {"path": str, "image": bool}

    def _add_input(path, image: bool = False) -> int:
        extra_inputs.append({"path": str(path), "image": image})
        return len(extra_inputs)  # 1-based; 0 is the source

    fc_parts = []

    # ================= Video chain =================
    cur = "[0:v]"
    has_vfilter = False
    vstep_n = 0

    def _video_step(chain: str) -> None:
        nonlocal cur, has_vfilter, vstep_n
        lbl = f"[vt{vstep_n}]"
        vstep_n += 1
        fc_parts.append(cur + chain + lbl)
        cur = lbl
        has_vfilter = True

    def _overlay_step(overlay_label: str, chain: str) -> None:
        nonlocal cur, has_vfilter, vstep_n
        lbl = f"[vt{vstep_n}]"
        vstep_n += 1
        fc_parts.append(cur + overlay_label + chain + lbl)
        cur = lbl
        has_vfilter = True

    # ---- Text (drawtext) — before cuts so times == short timeline ----
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
        font = _fontfile_value(bold, str(layer.get("font", "") or ""))
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
        if str(layer.get("animation", "")) in ("pop", "typewriter"):
            d += f":alpha={_ffmpeg_quote(f'clip((t-{t0:.3f})/0.3,0,1)')}"
        text_draws.append(d)

    if text_draws:
        _video_step(",".join(text_draws))

    # ---- Logo / watermark ----
    if logo and logo.get("file"):
        logo_path = out_dir / str(logo["file"])
        if logo_path.exists():
            canvas_w, canvas_h = _video_dims(src)
            scale = float(logo.get("scale", 0.12) or 0.12)
            opacity = float(logo.get("opacity", 1.0) or 1.0)
            px_w = max(4, int(canvas_w * scale))
            x = int(canvas_w * (float(logo.get("x", 3) or 3) / 100.0))
            y = int(canvas_h * (float(logo.get("y", 3) or 3) / 100.0))
            idx = _add_input(logo_path, image=True)
            if opacity >= 1.0:
                fc_parts.append(f"[{idx}:v]scale={px_w}:-1:flags=lanczos[lg]")
            else:
                fc_parts.append(
                    f"[{idx}:v]scale={px_w}:-1:flags=lanczos,format=rgba,"
                    f"colorchannelmixer=aa={opacity:.3f}[lg]"
                )
            _overlay_step("[lg]", f"overlay={x}:{y}")

    # ---- Stock / B-roll PiP ----
    canvas_w, canvas_h = _video_dims(src)
    for si, s in enumerate(stock_layers):
        s_file = str(s.get("file", ""))
        if not s_file:
            continue
        s_path = out_dir / s_file
        if not s_path.exists():
            continue
        t0 = max(0.0, float(s.get("start", 0)) - start)
        t1 = min(duration, float(s.get("end", duration)) - start)
        if t1 <= t0:
            continue
        sx = float(s.get("x", 10) or 10)
        sy = float(s.get("y", 60) or 60)
        sw_pct = float(s.get("scale", 40) or 40)
        opacity = _clampf(s.get("opacity", 1.0))
        px_w = max(4, int(canvas_w * sw_pct / 100.0))
        x = int(canvas_w * sx / 100.0)
        y = int(canvas_h * sy / 100.0)
        dur_s = t1 - t0
        idx = _add_input(s_path, image=bool(s.get("image")))
        chain = f"[{idx}:v]scale={px_w}:-1:flags=lanczos,format=rgba"
        if dur_s > 0.4:
            fd = min(0.15, dur_s / 2)
            chain += (
                f",fade=t=in:st=0:d={fd:.3f},fade=t=out:st={max(0.0, dur_s - fd):.3f}:d={fd:.3f}"
            )
        if opacity < 1.0:
            chain += f",colorchannelmixer=aa={opacity:.3f}"
        lbl = f"[so{si}]"
        fc_parts.append(chain + lbl)
        _overlay_step(
            lbl,
            f"overlay=x={x}:y={y}:eof_action=pass:"
            f"enable={_ffmpeg_quote(f'between(t,{t0:.3f},{t1:.3f})')}",
        )

    # ---- Cuts (compact the timeline AFTER overlays) ----
    local_cuts = []
    for s, e in cuts:
        try:
            ls = max(0.0, float(s) - start)
            le = min(duration, float(e) - start)
        except (TypeError, ValueError):
            continue
        if le > ls + 0.05:
            local_cuts.append((ls, le))
    if local_cuts:
        cut_expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in local_cuts)
        _video_step(f"select='not({cut_expr})',setpts=N/FRAME_RATE/TB")

    # ---- Filters ----
    fchain = _build_filter_chain(filters)
    if fchain:
        _video_step(fchain)

    # ---- Open / close effects ----
    open_eff = effects.get("open") or {}
    close_eff = effects.get("close") or {}
    okind = str(open_eff.get("kind", "none"))
    odur = _clampf(open_eff.get("dur", 0.5), 0.1, max(0.1, duration))
    ckind = str(close_eff.get("kind", "none"))
    cdur = _clampf(close_eff.get("dur", 0.5), 0.1, max(0.1, duration))

    stream_eff = []
    if okind == "zoom_in":
        e = f"(1-min(t/{odur:.3f},1))"
        stream_eff.append(
            f"scale=w='trunc(iw*(1+0.12*{e})/2)*2':h='trunc(ih*(1+0.12*{e})/2)*2':flags=lanczos:eval=frame"
        )
        stream_eff.append(
            f"crop=w={canvas_w}:h={canvas_h}:x='(iw-{canvas_w})/2':y='(ih-{canvas_h})/2'"
        )
    elif okind == "fade_in":
        stream_eff.append(f"fade=t=in:st=0:d={odur:.3f}")
    if ckind == "fade_out":
        stream_eff.append(f"fade=t=out:st={max(0.0, duration - cdur):.3f}:d={cdur:.3f}")
    elif ckind == "zoom_out":
        e = f"(min(t/{cdur:.3f},1))"
        stream_eff.append(
            f"scale=w='trunc(iw*(1+0.12*{e})/2)*2':h='trunc(ih*(1+0.12*{e})/2)*2':flags=lanczos:eval=frame"
        )
        stream_eff.append(
            f"crop=w={canvas_w}:h={canvas_h}:x='(iw-{canvas_w})/2':y='(ih-{canvas_h})/2'"
        )
    elif ckind == "glitch":
        g0 = max(0.0, duration - cdur)
        c = f"(clip((t-{g0:.3f})/{cdur:.3f},0,1))"
        stream_eff.append(
            f"scale=w='trunc(iw*(1+0.05*sin(t*400)*{c})/2)*2':"
            f"h='trunc(ih*(1+0.05*sin(t*400)*{c})/2)*2':flags=lanczos:eval=frame"
        )
        stream_eff.append(
            f"crop=w={canvas_w}:h={canvas_h}:x='(iw-{canvas_w})/2':y='(ih-{canvas_h})/2'"
        )
        stream_eff.append(f"hue=h='25*sin(t*450)*{c}'")
    if stream_eff:
        _video_step(",".join(stream_eff))

    def _add_flash_overlay(fade_chain: str) -> None:
        lbl = f"[fl{vstep_n}]"
        fc_parts.append(
            f"color=c=white:s={canvas_w}x{canvas_h}:r=30,format=rgba{fade_chain}{lbl}"
        )
        _overlay_step(lbl, "overlay=0:0:eof_action=pass")

    if okind == "flash":
        _add_flash_overlay(
            f",fade=t=in:st=0:d={odur:.3f}:alpha=1,"
            f"fade=t=out:st={odur:.3f}:d={odur:.3f}:alpha=1"
        )
    if ckind == "glitch":
        g0 = max(0.0, duration - cdur)
        half = max(0.05, cdur * 0.5)
        _add_flash_overlay(
            f",fade=t=in:st={g0:.3f}:d={half:.3f}:alpha=1,"
            f"fade=t=out:st={min(duration, g0 + half):.3f}:d={half:.3f}:alpha=1"
        )
    if ckind == "blur_out":
        b0 = max(0.0, duration - cdur)
        lbl = f"[fl{vstep_n}]"
        fc_parts.append(
            f"{cur}boxblur=lr=12:lp=4,format=rgba,"
            f"fade=t=in:st={b0:.3f}:d={cdur:.3f}:alpha=1{lbl}"
        )
        _overlay_step(lbl, "overlay=0:0:eof_action=pass")

    if has_vfilter and cur != "[vout]":
        fc_parts.append(f"{cur}null[vout]")

    # ================= Audio chain =================
    needs_audio = (
        bool(bgm_layers) or bool(sfx_layers) or bool(local_cuts)
        or abs(source_volume - 1.0) > 1e-6 or enhance > 0
    )
    if needs_audio:
        src_chain = f"[0:a]atrim=0:{duration:.3f}"
        if abs(source_volume - 1.0) > 1e-6:
            src_chain += f",volume={source_volume:.3f}"
        if enhance > 0:
            src_chain += "," + _voice_enhance_chain(enhance)
        src_chain += ",asetpts=PTS-STARTPTS[a_src]"
        fc_parts.append(src_chain)

        bgm_labels = []
        for bi, layer in enumerate(bgm_layers):
            audio_file = str(layer.get("file", ""))
            if not audio_file:
                continue
            audio_path = out_dir / audio_file
            if not audio_path.exists():
                continue
            lstart = float(layer.get("start", 0) or 0)
            volume = _clampf(layer.get("volume", 0.15), 0, 2)
            delay_ms = int(max(0, lstart - start) * 1000)
            start_off = max(0.0, lstart - start)
            need = max(0.1, duration - start_off)
            f_dur, f_sr = _probe_audio_info(audio_path)
            size = int((f_dur or 60) * f_sr)
            idx = _add_input(audio_path)
            lbl = f"abgm{bi}"
            bgm_labels.append(lbl)
            fc_parts.append(
                f"[{idx}:a]volume={volume:.3f},aloop=loop=-1:size={size},"
                f"adelay={delay_ms}:all=1,atrim=0:{need:.3f},asetpts=PTS-STARTPTS[{lbl}]"
            )

        sfx_labels = []
        for si, layer in enumerate(sfx_layers):
            audio_file = str(layer.get("file", ""))
            if not audio_file:
                continue
            audio_path = out_dir / audio_file
            if not audio_path.exists():
                continue
            lstart = float(layer.get("start", 0) or 0)
            volume = _clampf(layer.get("volume", 1.0), 0, 3)
            delay_ms = int(max(0, lstart - start) * 1000)
            idx = _add_input(audio_path)
            lbl = f"asfx{si}"
            sfx_labels.append(lbl)
            fc_parts.append(
                f"[{idx}:a]volume={volume:.3f},adelay={delay_ms}:all=1,apad[{lbl}]"
            )

        mixed = "[a_src]"
        if bgm_labels:
            mixed_labels = []
            if ducking > 0:
                thr = 0.08 - 0.079 * ducking
                ratio = 1 + 18 * ducking
                att = 40 - 30 * ducking
                rel = 120 + 280 * ducking
                for lbl in bgm_labels:
                    fc_parts.append(
                        f"[{lbl}][a_src]sidechaincompress=threshold={thr:.3f}:"
                        f"ratio={ratio:.2f}:attack={att:.1f}:release={rel:.1f}[{lbl}_d]"
                    )
                    mixed_labels.append(f"[{lbl}_d]")
            else:
                mixed_labels = [f"[{lbl}]" for lbl in bgm_labels]
            fc_parts.append(
                f"[a_src]{''.join(mixed_labels)}amix=inputs={1 + len(mixed_labels)}:"
                f"duration=first:dropout_transition=2[amix0]"
            )
            mixed = "[amix0]"

        for si, lbl in enumerate(sfx_labels):
            fc_parts.append(
                f"{mixed}[{lbl}]amix=inputs=2:duration=first:dropout_transition=0"
                f"[amix{si + 1}]"
            )
            mixed = f"[amix{si + 1}]"

        if local_cuts:
            cut_expr = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in local_cuts)
            fc_parts.append(f"{mixed}aselect='not({cut_expr})',asetpts=N/SR/TB[aout]")
        else:
            fc_parts.append(f"{mixed}anull[aout]")

    has_afilter = needs_audio

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    # -ss/-t MUST precede -i so they act as INPUT options. As output options
    # they do not reliably limit a filter_complex-mapped output duration.
    cmd += ["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    for extra in extra_inputs:
        if extra["image"]:
            cmd += ["-loop", "1"]
        cmd += ["-i", extra["path"]]
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
    subprocess.run(cmd, check=True, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)


@csrf_exempt
def upload_audio(request, video_id):
    """Store an uploaded audio file for use as a bgm or sfx layer.

    kind=bgm (default) goes to output/audio_layers/, kind=sfx to output/sfx/.
    """
    if request.method != "POST" or not request.FILES.get("file"):
        return JsonResponse({"error": "no file"}, status=400)

    f = request.FILES["file"]
    kind = request.POST.get("kind", "bgm")
    sub_name = "sfx" if kind == "sfx" else "audio_layers"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)
    sub = Path(settings.OUTPUT_DIR) / sub_name
    sub.mkdir(parents=True, exist_ok=True)
    safe = f"{int(time.time())}_{name}"
    dest = sub / safe
    with open(dest, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    return JsonResponse({
        "file": f"{sub_name}/{safe}",
        "kind": kind,
        "url": reverse("serve_output", args=[f"{sub_name}/{safe}"]),
    })


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


# ── Fonts (Windows typefaces for text layers) ────────────────────────

_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

# Curated set with proper display names; falls back to a directory scan.
_CURATED_FONTS = [
    ("Arial", "arial.ttf"), ("Arial Bold", "arialbd.ttf"), ("Arial Black", "ariblk.ttf"),
    ("Calibri", "calibri.ttf"), ("Calibri Bold", "calibrib.ttf"),
    ("Cambria", "cambria.ttc"), ("Cambria Bold", "cambriab.ttf"),
    ("Georgia", "georgia.ttf"), ("Georgia Bold", "georgiab.ttf"),
    ("Impact", "impact.ttf"),
    ("Segoe UI", "segoeui.ttf"), ("Segoe UI Bold", "segoeuib.ttf"),
    ("Segoe UI Black", "seguibl.ttf"),
    ("Tahoma", "tahoma.ttf"), ("Tahoma Bold", "tahomabd.ttf"),
    ("Times New Roman", "times.ttf"), ("Times New Roman Bold", "timesbd.ttf"),
    ("Trebuchet MS", "trebuc.ttf"), ("Trebuchet MS Bold", "trebucbd.ttf"),
    ("Verdana", "verdana.ttf"), ("Verdana Bold", "verdanab.ttf"),
]


def font_list(request):
    """Return available Windows font filenames for the text-layer picker."""
    found = []
    seen = set()
    for name, fname in _CURATED_FONTS:
        if (_FONT_DIR / fname).exists():
            found.append({"name": name, "file": fname})
            seen.add(fname.lower())
    try:
        extra = {}
        for p in sorted(_FONT_DIR.glob("*.ttf")):
            fn = p.name
            if fn.lower() in seen:
                continue
            extra[fn] = fn.replace("-", " ").replace("_", " ").rsplit(".", 1)[0].title()
        for fname, name in list(extra.items())[:160]:
            found.append({"name": name, "file": fname})
    except OSError:
        pass
    return JsonResponse({"fonts": found})


# ── SFX synthesis (server-side numpy -> WAV) ─────────────────────────

_SFX_KINDS = {"swoosh", "pop", "bass_drop", "shutter"}
_SFX_SR = 44100


def _synth_tone(freqs, dur, env_fn, noise=0.0, seed=0):
    import numpy as np
    rng = np.random.default_rng(seed)
    n = int(_SFX_SR * dur)
    t = np.arange(n) / _SFX_SR
    if callable(freqs):
        f = freqs(t)
    else:
        f = np.full(n, freqs)
    phase = 2 * np.pi * np.cumsum(f) / _SFX_SR
    sig = np.sin(phase)
    if noise > 0:
        sig = sig * (1 - noise) + rng.normal(0, 1, n) * noise
    env = env_fn(t)
    return sig * env


def _synth_sfx(kind: str) -> "tuple[np.ndarray, int]":
    """Synthesize a short sound effect as float32 samples in [-1, 1]."""
    import numpy as np

    if kind == "swoosh":
        # Band-swept noise whoosh: rising carrier + airy noise.
        dur = 1.1
        def freqs(t): return 250 + 2400 * (t / dur) ** 1.5
        def env(t): return np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
        sig = _synth_tone(freqs, dur, env, noise=0.55, seed=1)
    elif kind == "pop":
        # Short click: pitch falls 900 -> 220 Hz with a sharp decay.
        dur = 0.16
        def freqs(t): return 220 + 680 * np.exp(-t * 30)
        def env(t): return np.exp(-t * 22) * np.minimum(1, t * 2000)
        sig = _synth_tone(freqs, dur, env, noise=0.15, seed=2)
    elif kind == "bass_drop":
        # Sub drop: 90 -> 40 Hz sine with punchy attack + sub layer.
        dur = 1.2
        def freqs(t): return 40 + 50 * np.exp(-t * 2.2)
        def env(t): return np.minimum(1, t * 12) * np.exp(-t * 1.1)
        sig = _synth_tone(freqs, dur, env, noise=0.02, seed=3)
        t = np.arange(int(_SFX_SR * dur)) / _SFX_SR
        sig = 0.85 * sig + 0.35 * np.sin(2 * np.pi * 42 * t) * env(t)
    elif kind == "shutter":
        # DSLR shutter: two crisp clicks (impulse burst).
        dur = 0.18
        rng = np.random.default_rng(4)
        n = int(_SFX_SR * dur)
        t = np.arange(n) / _SFX_SR
        sig = np.zeros(n)
        for click_t in (0.0, 0.09):
            ci = int(click_t * _SFX_SR)
            k = max(1, int(_SFX_SR * 0.012))
            if ci + k <= n:
                sig[ci:ci + k] += rng.normal(0, 1, k) * np.linspace(1, 0, k) ** 1.5
        sig *= np.minimum(1, t * 4000)
        sig = np.clip(sig, -1, 1)
    else:
        raise ValueError(f"unknown sfx kind: {kind}")
    return np.clip(sig, -1, 1).astype(np.float32), _SFX_SR


def _write_wav(path: Path, samples, sr: int) -> None:
    import struct
    import wave
    pcm = (samples * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


@csrf_exempt
def sfx_generate(request, video_id, kind):
    """Synthesize a built-in sound effect and store it under output/sfx/."""
    if kind not in _SFX_KINDS:
        return JsonResponse({"error": "unknown sfx kind"}, status=400)
    try:
        samples, sr = _synth_sfx(kind)
    except Exception as e:
        return JsonResponse({"error": f"synthesis failed: {e}"}, status=500)
    sub = Path(settings.OUTPUT_DIR) / "sfx"
    sub.mkdir(parents=True, exist_ok=True)
    name = f"{kind}_{int(time.time() * 1000)}.wav"
    try:
        _write_wav(sub / name, samples, sr)
    except Exception as e:
        return JsonResponse({"error": f"write failed: {e}"}, status=500)
    return JsonResponse({
        "file": f"sfx/{name}",
        "url": reverse("serve_output", args=[f"sfx/{name}"]),
        "kind": kind,
        "duration": round(len(samples) / sr, 3),
    })


# ── Stock / B-roll (Pexels Video API, server-side proxy) ─────────────

def stock_search(request):
    """Proxy Pexels /videos/search and return mp4s with portrait preference."""
    from shorts_generator.config import PEXELS_API_KEY
    if not PEXELS_API_KEY:
        return JsonResponse({"error": "no_key"}, status=400)
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"error": "empty query"}, status=400)
    orientation = request.GET.get("orientation", "portrait")
    per_page = min(int(request.GET.get("per_page", "18") or 18), 80)

    import requests
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": orientation, "per_page": per_page},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return JsonResponse({"error": f"pexels request failed: {e}"}, status=502)

    videos = []
    for v in data.get("videos", []) or []:
        files = [f for f in (v.get("video_files") or []) if f.get("file_type") == "video/mp4"]
        if not files:
            continue
        files.sort(key=lambda f: (0 if f.get("width", 0) < f.get("height", 0) else 1, -f.get("width", 0)))
        best = files[0]
        if not best.get("link"):
            continue
        videos.append({
            "id": v.get("id"),
            "image": v.get("image") or "",
            "duration": v.get("duration") or 0,
            "width": best.get("width") or 0,
            "height": best.get("height") or 0,
            "url": best["link"],
        })
    return JsonResponse({"videos": videos})


@csrf_exempt
def stock_add(request, video_id):
    """Download a chosen stock clip into output/stock/."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    url = request.POST.get("url", "").strip()
    sid = request.POST.get("id", "").strip()
    if not url:
        return JsonResponse({"error": "no url"}, status=400)
    import requests
    sub = Path(settings.OUTPUT_DIR) / "stock"
    sub.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", sid or "stock")
    dest = sub / f"{name}_{int(time.time() * 1000)}.mp4"
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as out:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    out.write(chunk)
    except Exception as e:
        return JsonResponse({"error": f"download failed: {e}"}, status=502)
    return JsonResponse({
        "file": f"stock/{dest.name}",
        "url": reverse("serve_output", args=[f"stock/{dest.name}"]),
    })


# ── Captions from the transcript ─────────────────────────────────────

@csrf_exempt
def captions_for_clip(request, video_id, filename):
    """Map the source transcript's SRT segments onto a generated short.

    Filename must be short_<video_id>_c<clip_id:04d>.mp4. Each returned
    block is already in short-local time (offset by the clip start) and
    clamped to the clip's duration, ready to drop onto the Captions lane.
    """
    m = re.match(r"short_.*_c(\d{4})\.mp4$", filename)
    if not m:
        return JsonResponse({"error": "not a generated short filename"}, status=400)
    clip_id = int(m.group(1))
    try:
        clip = Clip.objects.get(id=clip_id, video_id=video_id)
    except Clip.DoesNotExist:
        return JsonResponse({"error": "clip not found"}, status=404)

    srt_path = Path(settings.OUTPUT_DIR) / f"source_{video_id}.srt"
    if not srt_path.exists():
        return JsonResponse({"error": "no transcript for this source"}, status=404)
    segments = _parse_srt(srt_path)
    clip_dur = max(0.1, clip.end_time - clip.start_time)

    blocks = []
    for i, seg in enumerate(segments):
        s = max(0.0, seg["start"] - clip.start_time)
        e = min(clip_dur, seg["end"] - clip.start_time)
        if e <= s:
            continue
        blocks.append({
            "id": i,
            "start": round(s, 3),
            "end": round(e, 3),
            "text": seg["text"],
        })
    return JsonResponse({
        "segments": blocks,
        "clip_start": clip.start_time,
        "clip_end": clip.end_time,
        "duration": round(clip_dur, 3),
    })


def _normalize_layers(raw) -> dict:
    """Coerce the editor's layers JSON into the renderer schema."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    out = {
        "text": [l for l in (raw.get("text") or []) if isinstance(l, dict)],
        "captions": [l for l in (raw.get("captions") or []) if isinstance(l, dict)],
        "stock": [l for l in (raw.get("stock") or []) if isinstance(l, dict)],
        "sfx": [l for l in (raw.get("sfx") or []) if isinstance(l, dict)],
        "bgm": [l for l in (raw.get("bgm") or []) if isinstance(l, dict)],
        "filters": [l for l in (raw.get("filters") or []) if isinstance(l, dict)],
        "logo": raw.get("logo") if isinstance(raw.get("logo"), dict) else None,
        "audioFx": raw.get("audioFx") if isinstance(raw.get("audioFx"), dict) else {},
        "effects": raw.get("effects") if isinstance(raw.get("effects"), dict) else {},
        "cuts": [list(c) for c in (raw.get("cuts") or [])],
        "source_volume": float(raw.get("source_volume", 1.0) or 1.0),
    }
    # Backward compat: the old editor sent "audio" + a boolean "ducking".
    if not out["bgm"] and raw.get("audio"):
        out["bgm"] = [l for l in raw["audio"] if isinstance(l, dict)]
    if not out["audioFx"].get("ducking") and "ducking" in raw:
        out["audioFx"]["ducking"] = 1.0 if raw.get("ducking") else 0.0
    return out


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

        layers = _normalize_layers(request.POST.get("layers", ""))

        # Normalise cuts: clamp, sort, merge overlaps (all on the full-clip axis).
        cuts = [list(c) for c in layers.get("cuts") or []]
        cuts.sort()
        merged_cuts = []
        for s, e in cuts:
            try:
                s = max(0.0, min(float(s), duration))
                e = max(0.0, min(float(e), duration))
            except (ValueError, TypeError):
                continue
            if e <= s:
                continue
            if merged_cuts and s < merged_cuts[-1][1]:
                merged_cuts[-1][1] = max(merged_cuts[-1][1], e)
            else:
                merged_cuts.append([s, e])
        layers["cuts"] = merged_cuts

        stem = src.stem
        trimmed = out_dir / f"{stem}_trimmed.mp4"
        n = 1
        while trimmed.exists():
            trimmed = out_dir / f"{stem}_trimmed_{n}.mp4"
            n += 1
        try:
            _render_layers(src, start, end, trimmed, layers, out_dir)
        except Exception as e:
            return HttpResponseRedirect(
                reverse("clip_editor", kwargs={"video_id": video_id})
                + f"?msg=Render failed: {e}"
            )
        bits = []
        if layers.get("text") or layers.get("captions"):
            n_t = len(layers.get("text") or []) + len(layers.get("captions") or [])
            bits.append(f"{n_t} text")
        if layers.get("logo"):
            bits.append("watermark")
        if layers.get("stock"):
            bits.append(f"{len(layers['stock'])} stock")
        if layers.get("bgm"):
            bits.append(f"{len(layers['bgm'])} music")
        if layers.get("sfx"):
            bits.append(f"{len(layers['sfx'])} sfx")
        if layers.get("filters"):
            bits.append(f"{len(layers['filters'])} filter")
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

"""Local clipping: ffmpeg subclip + per-template vertical crop.

Three stages per highlight (output is always 9:16):
  1. Cut the source video to [start, end] with ffmpeg. Video only — the
     final mux reads audio from the original source via input seek.
  2. OpenCV reads the cut, applies the template's composition strategy,
     writes a silent 9:16 video with optional text overlays / widgets.
  3. ffmpeg muxes the silent reframed video with audio from the original
     source (with input seek) to produce the final output.

Templates (from templates.txt + template.json spec):
  Stage & Solo Speaker : stage_solo_speaker
  Podcast & Dialogue   : podcast_split_screen

Audio is read from the original source rather than the cut clip. This
avoids a Windows file-lock race: the cut clip is only touched by OpenCV
(which releases it cleanly) and the ffmpeg child that produced it (which
has already exited). The previous design had ffmpeg read the cut clip
during mux, holding the file open right when the `finally` block tried
to delete it, producing `[WinError 32] The process cannot access the file
because it is being used by another process`.
"""
import gc
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

from ..config import LOCAL_OUTPUT_DIR
from ..progress import Progress


# Suppress console window pop-up on Windows when invoking ffmpeg.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_FFMPEG_TIMEOUT = 600  # 10 minutes per ffmpeg call
ASPECT_RATIO = "9:16"  # vertical 9:16 is the only output format this app produces

# ── 9:16 canvas spec (see newTemp.md) ───────────────────────────────
CANVAS_W = 1080
CANVAS_H = 1920
TOP_SAFE_H = int(CANVAS_H * 0.23)                   # 441px  — hook / UI safe zone (23%)
STAGE_H = int(CANVAS_H * 0.60)                      # 1152px — talking stage (60%)
BOTTOM_SAFE_H = CANVAS_H - TOP_SAFE_H - STAGE_H     # 327px  — name tag / TikTok UI safe zone (17%)
CAPTION_Y = 1330                        # centered caption baseline in px
CAPTION_BAND_TOP = 1180
CAPTION_BAND_BOTTOM = 1500
MAX_CAPTION_W = int(CANVAS_W * 0.8)     # 864px  — captions never exceed 80% width
MAX_CAPTION_WORDS = 5                   # words shown per caption batch (fixed block)
CAPTION_FONT_SCALE = 2.0                # large bold word-by-word caption font
CAPTION_FONT_THICK = 4                  # bold stroke for captions
CAPTION_ACCENT = (77, 145, 255)         # #ff914d in BGR — current word highlight


# ── Caption style support (Pillow TTF rendering) ──────────────────────
# Client presets are applied here: font token, color hex, position.
# OpenCV's built-in Hershey fonts can't render real brand fonts, so when
# Pillow is available the caption block is rasterized as an RGBA sprite and
# alpha-composited onto the frame. Falls back to the OpenCV renderer without.

_FONT_TOKEN_FILES = {
    "inter": ["segoeuib.ttf", "segoeui.ttf", "arialbd.ttf", "arial.ttf"],
    "serif": ["georgiab.ttf", "georgia.ttf", "timesbd.ttf", "times.ttf"],
    "mono": ["consolab.ttf", "consola.ttf", "courbd.ttf", "cour.ttf"],
}
_WINDOWS_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

_font_cache: Dict[Tuple[str, int], Any] = {}


def _resolve_font(token: str, size: int):
    key = (token or "inter", size)
    if key in _font_cache:
        return _font_cache[key]
    for name in _FONT_TOKEN_FILES.get(token or "inter", _FONT_TOKEN_FILES["inter"]):
        cand = _WINDOWS_FONT_DIR / name
        if cand.exists():
            try:
                font = ImageFont.truetype(str(cand), size)
                _font_cache[key] = font
                return font
            except Exception:
                continue
    font = ImageFont.load_default(size)
    _font_cache[key] = font
    return font


def _composite_rgba(canvas: "np.ndarray", rgba: "np.ndarray", x0: int, y0: int) -> "np.ndarray":
    """Alpha-composite an RGBA sprite onto an BGR canvas at (x0, y0)."""
    h, w = rgba.shape[:2]
    x1, y1 = min(canvas.shape[1], x0 + w), min(canvas.shape[0], y0 + h)
    if x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        return canvas
    alpha = (rgba[: y1 - y0, : x1 - x0, 3].astype(np.float32) / 255.0)[..., None]
    rgb = rgba[: y1 - y0, : x1 - x0, :3].astype(np.float32)
    bgr = rgb[..., ::-1]  # sprite is RGB; canvas is BGR
    roi = canvas[y0:y1, x0:x1].astype(np.float32)
    canvas[y0:y1, x0:x1] = (roi * (1 - alpha) + bgr * alpha).astype(np.uint8)
    return canvas


def _parse_hex(color: Optional[str]) -> Tuple[int, int, int]:
    try:
        h = (color or "#FFFFFF").lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 255, 255, 255


def _word_block_rgba(
    window: List[str],
    batch_start: int,
    current_idx: int,
    style: Optional[Dict],
) -> "np.ndarray":
    """Rasterize a caption block (max 5 words) as an RGBA sprite.

    All words are drawn in the client's caption color; the word currently
    being spoken sits on a rounded accent chip so the sync is readable even
    on mute. The whole block is one sprite pasted per frame.
    """
    base_rgb = _parse_hex((style or {}).get("color"))
    accent_rgb = (255, 145, 77)
    font = _resolve_font((style or {}).get("font"), 92)

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    space_w = probe.textlength(" ", font=font)

    # Wrap words onto up to two lines that fit MAX_CAPTION_W.
    lines: List[List[str]] = [[]]
    line_w = 0.0
    for w in window:
        ww = probe.textlength(w, font=font)
        if lines[-1] and line_w + ww > MAX_CAPTION_W:
            lines.append([])
            line_w = 0.0
        lines[-1].append(w)
        line_w += ww + space_w

    line_h = int(font.size * 1.25)
    block_w = int(max(sum(probe.textlength(w + " ", font=font) for w in ln) for ln in lines)) if lines else 1
    block_h = len(lines) * line_h

    img = Image.new("RGBA", (block_w + 60, block_h + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, block_w + 59, block_h + 29], radius=14, fill=(0, 0, 0, 175))

    y = 15
    idx = 0
    for line in lines:
        x = 30
        for w in line:
            abs_idx = batch_start + idx
            if abs_idx == current_idx:
                ww = d.textlength(w, font=font)
                d.rounded_rectangle([x - 8, y - 6, x + ww + 8, y + line_h - 8], radius=10, fill=accent_rgb + (235,))
                d.text((x, y), w, font=font, fill=(20, 20, 20, 255))
            else:
                d.text((x, y), w, font=font, fill=base_rgb + (255,))
            x += d.textlength(w, font=font) + space_w
            idx += 1
        y += line_h
    return np.array(img)


def _band_for_position(position: Optional[str], layout_type: str) -> Tuple[int, int]:
    if position == "top":
        return 320, 620
    if position == "center":
        return 720, 1300
    return CAPTION_BAND_TOP, CAPTION_BAND_BOTTOM


# ── Template specs (from template.json) ─────────────────────────────

# Each spec describes a layout type and optional stylings that the reframe
# function reads at render time.

TEMPLATE_SPECS: Dict[str, Dict[str, Any]] = {
    "stage_solo_speaker": {
        "label": "Stage & Solo Speaker",
        "category": "Talk & Conversation",
        "layout": {"type": "single_focus"},
        "typography": {"position": "lower_third", "font_scale": 1.1},
        "auto_framing": True,
    },
    "podcast_split_screen": {
        "label": "Podcast & Dialogue",
        "category": "Talk & Conversation",
        "layout": {"type": "split_vertical", "split_ratio": 0.5, "focus": "top"},
        "typography": {"position": "center", "max_lines": 2},
        "auto_framing": True,
    },
}

TEMPLATE_LABELS: Dict[str, str] = {k: v["label"] for k, v in TEMPLATE_SPECS.items()}

DEFAULT_TEMPLATE = "stage_solo_speaker"


# ── Helpers ─────────────────────────────────────────────────────────

def _ratio(aspect_ratio: str) -> float:
    """Parse '9:16' -> 9/16. Only 9:16 is supported; kept as a parser."""
    try:
        w, h = aspect_ratio.split(":")
        return float(w) / float(h)
    except (ValueError, ZeroDivisionError):
        return 9.0 / 16.0


def _cut_subclip(source_path: str, start: float, end: float, out_path: str) -> str:
    """Cut the source video to [start, end] with ffmpeg. Video only — the
    final mux reads audio from the original source via input seek, so
    re-encoding audio here would be wasted work."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", source_path,
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-an",
        out_path,
    ]
    subprocess.run(cmd, check=True, timeout=_FFMPEG_TIMEOUT, creationflags=_NO_WINDOW)
    return out_path


def _mux_audio(
    silent_path: str,
    out_path: str,
    source_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    in_path: Optional[str] = None,
) -> None:
    """Mux audio from the original source onto the silent reframed video."""
    if source_path is not None and start_time is not None and end_time is not None:
        duration = end_time - start_time
        audio_args = [
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", source_path,
        ]
    else:
        audio_args = ["-i", in_path] if in_path else []

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent_path,
        *audio_args,
        # Re-encode to H.264: OpenCV writes MPEG-4 Part 2 (mp4v), which
        # browsers cannot decode — the video track silently disappears.
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "1:a:0?",
        "-shortest",
        "-movflags", "+faststart",
        out_path,
    ]
    subprocess.run(cmd, check=True, timeout=_FFMPEG_TIMEOUT, creationflags=_NO_WINDOW)


def _opencv_temp(in_path: str) -> Tuple[str, str]:
    """Copy in_path to a temp location so OpenCV never locks the original.

    Returns (temp_path, original_path). On non-Windows the copy is skipped.
    """
    temp_path = in_path + ".opencv_temp.mp4"
    try:
        import shutil
        shutil.copy2(in_path, temp_path)
    except Exception:
        temp_path = in_path
    return temp_path, in_path


def _cleanup_temp(temp_path: str, in_path: str) -> None:
    """Remove the temp copy if one was created."""
    if temp_path != in_path:
        for _ in range(10):
            try:
                os.remove(temp_path)
                break
            except PermissionError:
                time.sleep(0.2)


# ── Reframe strategies ──────────────────────────────────────────────

def _open_cv() -> None:
    """Ensure opencv is importable (module-level import may have failed)."""
    if cv2 is None:
        raise RuntimeError(
            "opencv-contrib-python is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        )


def _get_frame_info(
    cap: "cv2.VideoCapture",
    progress: Optional[Progress],
) -> Tuple[int, int, float, int]:
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if progress is not None and total_frames > 0:
        progress.set_total(total_frames)
    return src_w, src_h, fps, total_frames


def _crop_dims(src_w: int, src_h: int) -> Tuple[int, int]:
    """Compute the largest 9:16 crop that fits inside (src_w, src_h)."""
    target_ratio = _ratio(ASPECT_RATIO)
    if target_ratio < src_w / src_h:
        crop_h = src_h
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(crop_w / target_ratio)
    crop_w = max(2, min(crop_w, src_w - (src_w % 2)))
    crop_h = max(2, min(crop_h, src_h - (src_h % 2)))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    return crop_w, crop_h


def _reframe_center(
    in_path: str,
    out_path: str,
    source_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    progress: Optional[Progress] = None,
) -> str:
    """Center-crop the clip to 9:16 — no face tracking.

    Ideal for gaming (focus on gameplay) and education (focus on slides).
    """
    _open_cv()

    temp_path, orig_path = _opencv_temp(in_path)
    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        if temp_path != orig_path:
            try: os.remove(temp_path)
            except Exception: pass
        raise RuntimeError(f"could not open {in_path}")

    src_w, src_h, fps, total_frames = _get_frame_info(cap, progress)
    crop_w, crop_h = _crop_dims(src_w, src_h)

    print(f"  [crop/center] {src_w}x{src_h} -> {crop_w}x{crop_h} @ 9:16", flush=True)

    cx, cy = src_w // 2, src_h // 2
    x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
    y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))

    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (crop_w, crop_h))

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cropped)
        if progress is not None and (frame_idx % 30 == 0 or total_frames == 0):
            progress.update(frame_idx)

    cap.release()
    writer.release()
    del cap, writer
    gc.collect()

    _mux_audio(silent_path, out_path, source_path, start_time, end_time, in_path)
    os.remove(silent_path)
    _cleanup_temp(temp_path, orig_path)
    return out_path


def _reframe_facetrack(
    in_path: str,
    out_path: str,
    source_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    progress: Optional[Progress] = None,
    zoom: float = 1.0,
) -> str:
    """Face-tracking crop to 9:16.

    Detects the largest face per frame and smoothly tracks it. The *zoom*
    parameter can be set >1.0 for entertainment-style punch-in effects.
    """
    _open_cv()

    temp_path, orig_path = _opencv_temp(in_path)
    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        if temp_path != orig_path:
            try: os.remove(temp_path)
            except Exception: pass
        raise RuntimeError(f"could not open {in_path}")

    src_w, src_h, fps, total_frames = _get_frame_info(cap, progress)
    crop_w, crop_h = _crop_dims(src_w, src_h)

    # Apply zoom: shrink the crop window so the centre area is enlarged.
    if zoom > 1.0:
        crop_w = int(crop_w / zoom)
        crop_h = int(crop_h / zoom)
        crop_w -= crop_w % 2
        crop_h -= crop_h % 2
        crop_w = max(2, crop_w)
        crop_h = max(2, crop_h)

    print(
        f"  [crop/facetrack] {src_w}x{src_h} -> {crop_w}x{crop_h} @ 9:16"
        + (f" zoom={zoom:.2f}x" if zoom > 1.0 else ""),
        flush=True,
    )

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(silent_path, fourcc, fps, (crop_w, crop_h))

    last_center: Optional[Tuple[int, int]] = None
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
        )
        if len(faces) > 0:
            x, y, w_box, h_box = max(faces, key=lambda f: f[2] * f[3])
            cx = x + w_box // 2
            cy = y + h_box // 2
            if last_center is None:
                last_center = (cx, cy)
            else:
                lx, ly = last_center
                sx = int(lx + (cx - lx) * 0.2)
                sy = int(ly + (cy - ly) * 0.2)
                dx = sx - lx
                dy = sy - ly
                dist = math.sqrt(dx * dx + dy * dy)
                if dist > _PRE_SCAN_MAX_MOVE:
                    scale = _PRE_SCAN_MAX_MOVE / dist
                    sx = int(lx + dx * scale)
                    sy = int(ly + dy * scale)
                last_center = (sx, sy)
        if last_center is None:
            last_center = (src_w // 2, src_h // 2)

        cx, cy = last_center
        x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
        y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
        cropped = frame[y0:y0 + crop_h, x0:x0 + crop_w]
        writer.write(cropped)

        if progress is not None and (frame_idx % 30 == 0 or total_frames == 0):
            progress.update(frame_idx)

    cap.release()
    writer.release()
    del cap, writer
    gc.collect()

    _mux_audio(silent_path, out_path, source_path, start_time, end_time, in_path)
    os.remove(silent_path)
    _cleanup_temp(temp_path, orig_path)
    return out_path


# ── Two-pass pre-scan & render ───────────────────────────────────────

# Pre-scan samples per second of video. Lower = faster scan, fewer data points.
_PRE_SCAN_FPS = 1.0

# Median filter window (in pre-scan samples). Wider = smoother but less responsive.
_PRE_SCAN_MEDIAN_WINDOW = 3

# Maximum crop-center displacement per frame (pixels at src resolution).
_PRE_SCAN_MAX_MOVE = 30.0


def _crop_rect(
    cx: int, cy: int, src_w: int, src_h: int, crop_w: int, crop_h: int,
) -> Tuple[int, int, int, int]:
    """Return (x0, y0, x1, y1) for a 9:16 crop centered on (cx, cy)."""
    x0 = max(0, min(src_w - crop_w, cx - crop_w // 2))
    y0 = max(0, min(src_h - crop_h, cy - crop_h // 2))
    return x0, y0, x0 + crop_w, y0 + crop_h


def _render_contain(
    frame: "np.ndarray",
    out_w: int, out_h: int,
    caption_pct: float = 0.0,
    bg_style: str = "blur",
) -> "np.ndarray":
    """Scale source to fit inside *out_w* x *out_h* canvas (contain mode).

    The source is never cropped — it is scaled to fit within the 9:16
    canvas maintaining its natural aspect ratio. The remaining area is
    filled according to *bg_style*:

      "blur"  -> heavily blurred version of the source (default)
      "solid" -> solid dark color *(20, 20, 20)*

    When *caption_pct* > 0, a semi-transparent black strip is added at
    the bottom for subtitle readability.
    """
    h, w = frame.shape[:2]

    scale = min(out_w / w, out_h / h)
    sw = int(w * scale)
    sh = int(h * scale)
    scaled = cv2.resize(frame, (sw, sh))

    # Build background
    if bg_style == "solid":
        bg = np.full((out_h, out_w, 3), 20, dtype=np.uint8)
    else:
        bg = cv2.resize(frame, (out_w, out_h))
        ksize = min(51, (out_h // 2) * 2 + 1, (out_w // 2) * 2 + 1)
        ksize = max(3, ksize | 1)
        bg = cv2.GaussianBlur(bg, (ksize, ksize), 0)

    # Overlay sharp source centered
    x_off = (out_w - sw) // 2
    y_off = (out_h - sh) // 2
    view = bg[y_off:y_off + sh, x_off:x_off + sw]
    np.copyto(view, scaled)

    # Captions strip at bottom
    if caption_pct > 0:
        strip_h = int(out_h * caption_pct)
        overlay = np.full((strip_h, out_w, 3), 0, dtype=np.uint8)
        cv2.addWeighted(bg[-strip_h:, :, :], 0.5, overlay, 0.5, 0, bg[-strip_h:, :, :])

    return bg


def _render_letterbox(
    frame: "np.ndarray",
    out_w: int, out_h: int,
    container_aspect: float = 16.0 / 9.0,
    vertical_align: str = "center",
) -> "np.ndarray":
    h, w = frame.shape[:2]
    cw = out_w
    ch = int(out_w / container_aspect)
    if ch > out_h:
        ch = out_h
        cw = int(out_h * container_aspect)

    scale = min(cw / w, ch / h)
    sw = int(w * scale)
    sh = int(h * scale)
    scaled = cv2.resize(frame, (sw, sh))

    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    if vertical_align == "lower_middle":
        y_off = out_h - ch + (ch - sh) // 2
    else:
        y_off = (out_h - ch) // 2 + (ch - sh) // 2
    x_off = (out_w - sw) // 2
    canvas[y_off:y_off + sh, x_off:x_off + sw] = scaled
    return canvas


def _pre_scan_trajectory(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
) -> Tuple[List[Tuple[int, int]], bool]:
    """Pass 1: sample at *PRE_SCAN_FPS, detect ALL faces, return a smooth
    per-frame crop-center trajectory + whether padded blur was triggered.

    Unlike naive single-face tracking, this computes the *union bounding
    box* of ALL detected faces per sample frame. The tracking target is
    the center of the union, keeping every face in frame. When the union
    is too wide for 9:16, *use_blur* is set and the renderer falls back
    to blurred fill.

    Returns (trajectory, use_blur) where:
      *trajectory* is a list of (cx, cy) with length == total_frames.
      *use_blur* is True when the scene content does not fit 9:16.
    """
    sample_every = max(1, int(fps / _PRE_SCAN_FPS))

    # ── Phase 1: collect ALL face boxes per sample ──
    # Each entry: (frame_idx, union_cx, union_cy, union_width, face_count)
    raw: List[Tuple[int, Optional[int], Optional[int], int, int]] = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
            )
            if len(faces) > 0:
                xs = [f[0] for f in faces]
                ys = [f[1] for f in faces]
                xe = [f[0] + f[2] for f in faces]
                ye = [f[1] + f[3] for f in faces]
                u_cx = (min(xs) + max(xe)) // 2
                u_cy = (min(ys) + max(ye)) // 2
                u_w = max(xe) - min(xs)
                raw.append((frame_idx, u_cx, u_cy, u_w, len(faces)))
            else:
                raw.append((frame_idx, None, None, 0, 0))
        frame_idx += 1

    # ── Phase 2: forward-fill missing detections ──
    last_cx, last_cy = src_w // 2, src_h // 2
    filled: List[Tuple[int, int, int, int]] = []  # (frame_idx, cx, cy, face_count)
    for det in raw:
        if det[1] is not None:
            last_cx, last_cy = det[1], det[2]
        filled.append((det[0], last_cx, last_cy, det[4]))

    # ── Phase 3: median filter over temporal window ──
    medianed: List[Tuple[int, int]] = []
    half = _PRE_SCAN_MEDIAN_WINDOW // 2
    for i in range(len(filled)):
        window = filled[max(0, i - half):min(len(filled), i + half + 1)]
        cx = int(np.median([c[1] for c in window]))
        cy = int(np.median([c[2] for c in window]))
        medianed.append((cx, cy))

    # ── Phase 4: EMA smooth (camera-like easing) ──
    ema: List[Tuple[int, int]] = []
    prev = (src_w // 2, src_h // 2)
    for cx, cy in medianed:
        sx = int(prev[0] + (cx - prev[0]) * 0.3)
        sy = int(prev[1] + (cy - prev[1]) * 0.3)
        ema.append((sx, sy))
        prev = (sx, sy)

    # ── Detect blur-fill condition ──
    # Use the MEDIAN union width across samples (not max) so a single
    # noisy detection frame does not trigger blur fill for the whole clip.
    crop_w, _ = _crop_dims(src_w, src_h)
    union_widths = [d[3] for d in raw if d[1] is not None]
    median_union_w = int(np.median(union_widths)) if union_widths else 0
    use_blur = median_union_w > crop_w * 0.8

    # ── Phase 5: interpolate samples -> per-frame trajectory ──
    def _smoothstep(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    trajectory: List[Tuple[int, int]] = []
    for fi in range(total_frames):
        si = fi // sample_every
        si = min(si, len(ema) - 1)
        ni = min(si + 1, len(ema) - 1)
        t = (fi % sample_every) / sample_every if sample_every > 0 else 0.0
        st = _smoothstep(t)
        ex = int(ema[si][0] + (ema[ni][0] - ema[si][0]) * st)
        ey = int(ema[si][1] + (ema[ni][1] - ema[si][1]) * st)
        trajectory.append((ex, ey))

    return trajectory, use_blur


def _pre_scan_trajectory_pair(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """Pass 1 for the podcast split: two smoothed trajectories — one per
    speaker half (left half -> top panel, right half -> bottom panel).

    Faces are separated by whether their center-x sits left or right of the
    source midpoint, so each panel tracks its own speaker. Halves with no
    face detections fall back to their natural center.

    Returns (traj_left, traj_right) with length == total_frames each.
    """
    sample_every = max(1, int(fps / _PRE_SCAN_FPS))
    mid = src_w // 2

    # raw per-sample points per half: (frame_idx, cx, cy) or None
    raw_left: List[Tuple[int, Optional[int], Optional[int]]] = []
    raw_right: List[Tuple[int, Optional[int], Optional[int]]] = []
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
            )
            lx = ly = rx = ry = None
            if len(faces) > 0:
                for (x, y, w_box, h_box) in faces:
                    fcx = x + w_box // 2
                    fcy = y + h_box // 2
                    if fcx < mid:
                        lx, ly = fcx, fcy
                    else:
                        rx, ry = fcx, fcy
            raw_left.append((frame_idx, lx, ly))
            raw_right.append((frame_idx, rx, ry))
        frame_idx += 1

    def _build(raw: List[Tuple[int, Optional[int], Optional[int]]], default_xy: Tuple[int, int]) -> List[Tuple[int, int]]:
        last_cx, last_cy = default_xy
        filled: List[Tuple[int, int]] = []
        for det in raw:
            if det[1] is not None:
                last_cx, last_cy = det[1], det[2]
            filled.append((last_cx, last_cy))
        half = _PRE_SCAN_MEDIAN_WINDOW // 2
        medianed = []
        for i in range(len(filled)):
            window = filled[max(0, i - half):min(len(filled), i + half + 1)]
            medianed.append((int(np.median([c[0] for c in window])), int(np.median([c[1] for c in window]))))
        ema: List[Tuple[int, int]] = []
        prev = default_xy
        for cx, cy in medianed:
            sx = int(prev[0] + (cx - prev[0]) * 0.3)
            sy = int(prev[1] + (cy - prev[1]) * 0.3)
            ema.append((sx, sy))
            prev = (sx, sy)
        def _smoothstep(t: float) -> float:
            return t * t * (3.0 - 2.0 * t)
        traj: List[Tuple[int, int]] = []
        for fi in range(total_frames):
            si = fi // sample_every
            si = min(si, len(ema) - 1)
            ni = min(si + 1, len(ema) - 1)
            t = (fi % sample_every) / sample_every if sample_every > 0 else 0.0
            st = _smoothstep(t)
            ex = int(ema[si][0] + (ema[ni][0] - ema[si][0]) * st)
            ey = int(ema[si][1] + (ema[ni][1] - ema[si][1]) * st)
            traj.append((ex, ey))
        return traj

    return (
        _build(raw_left, (src_w // 4, src_h // 2)),
        _build(raw_right, (src_w * 3 // 4, src_h // 2)),
    )


# ── Layout helpers (stateless, receive pre-computed crop center) ─────

def _crop_single_focus(
    frame: "np.ndarray",
    crop_w: int, crop_h: int,
    cx: int, cy: int,
) -> "np.ndarray":
    """Extract 9:16 region centered on (cx, cy)."""
    h, w = frame.shape[:2]
    x0 = max(0, min(w - crop_w, cx - crop_w // 2))
    y0 = max(0, min(h - crop_h, cy - crop_h // 2))
    return frame[y0:y0 + crop_h, x0:x0 + crop_w].copy()


def _crop_split_vertical(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    crop_w: int, crop_h: int,
    cx: int, cy: int,
    split_ratio: float,
    focus: str,
) -> "np.ndarray":
    """Split the 9:16 canvas into two stacked regions."""
    base = _crop_single_focus(frame, crop_w, crop_h, cx, cy)
    split_y = int(crop_h * split_ratio)
    if focus == "top":
        r1 = cv2.resize(base[:split_y, :], (crop_w, split_y))
        r2 = cv2.resize(base, (crop_w, crop_h - split_y))
    else:
        r1 = cv2.resize(base, (crop_w, split_y))
        r2 = cv2.resize(base[split_y:, :], (crop_w, crop_h - split_y))
    return cv2.vconcat([r1, r2])


def _crop_layered(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    crop_w: int, crop_h: int,
    cx: int, cy: int,
    overlay_size: float,
) -> "np.ndarray":
    """Full 9:16 background + circular PiP overlay in bottom-right."""
    bg = _crop_single_focus(frame, crop_w, crop_h, cx, cy)
    overlay_diameter = int(min(crop_w, crop_h) * overlay_size)
    overlay_radius = overlay_diameter // 2
    mid_x, mid_y = src_w // 2, src_h // 2

    o_rgn = frame[
        mid_y - overlay_radius:mid_y + overlay_radius,
        mid_x - overlay_radius:mid_x + overlay_radius,
    ]
    o_rgn = cv2.resize(o_rgn, (overlay_diameter, overlay_diameter))

    mask = np.zeros((overlay_diameter, overlay_diameter), dtype=np.uint8)
    cv2.circle(mask, (overlay_radius, overlay_radius), overlay_radius, 255, -1)

    ox = crop_w - overlay_diameter - 20
    oy = crop_h - overlay_diameter - 20

    fmask = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
    roi = bg[oy:oy + overlay_diameter, ox:ox + overlay_diameter]
    blended = (roi * (1 - fmask) + o_rgn.astype(np.float32) * fmask).astype(np.uint8)
    bg[oy:oy + overlay_diameter, ox:ox + overlay_diameter] = blended
    return bg


def _render_stage_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx: int, cy: int,
) -> "np.ndarray":
    """Template 1 (Stage & Solo Speaker): video confined to the PRIMARY
    STAGE region (1080x1152 px at y 441-1593) on a solid-black 1080x1920
    canvas.

    Top safe zone (0-441px) and bottom safe zone (1593-1920px) are pure
    black. The source is cropped to the stage's aspect ratio (0.9375),
    centered on the tracked head & torso, and scaled to fill the stage —
    the head sits near the top of the stage, torso below.
    """
    canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
    stage_w, stage_h = CANVAS_W, STAGE_H          # 1080 x 1152 primary stage (60%)
    stage_y0 = TOP_SAFE_H                         # 441px (23%)
    aspect = stage_w / stage_h                  # 0.9375

    if src_h * aspect <= src_w:
        ch = src_h
        cw = int(ch * aspect)
    else:
        cw = src_w
        ch = int(cw / aspect)
    cw -= cw % 2
    ch -= ch % 2

    # Horizontal center on the tracked face; vertically keep the head near
    # the top of the stage so head + torso fill the zone.
    x0 = max(0, min(src_w - cw, cx - cw // 2))
    head_frac = 0.20
    y0 = max(0, min(src_h - ch, cy - int(ch * head_frac)))
    region = frame[y0:y0 + ch, x0:x0 + cw]
    stage = cv2.resize(region, (stage_w, stage_h))
    canvas[stage_y0:stage_y0 + stage_h, :, :] = stage
    return canvas


def _render_podcast_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx_left: int, cy_left: int,
    cx_right: int, cy_right: int,
) -> "np.ndarray":
    """Template 2 (Podcast & Dialogue): two stacked 9:8 panels (1080x960
    each) on the 1080x1920 canvas.

    Each panel crops a 9:8 region around its speaker's tracked face and is
    scaled down to panel size. The left-half trajectory feeds the top panel,
    the right-half trajectory feeds the bottom panel.
    """
    panel_w, panel_h = CANVAS_W, CANVAS_H // 2  # 1080 x 960 (9:8)
    aspect = 9.0 / 8.0

    def _panel(cx: int, cy: int) -> "np.ndarray":
        if src_h * aspect <= src_w:
            ch = src_h
            cw = int(ch * aspect)
        else:
            cw = src_w
            ch = int(cw / aspect)
        x0 = max(0, min(src_w - cw, cx - cw // 2))
        y0 = max(0, min(src_h - ch, cy - ch // 2))
        region = frame[y0:y0 + ch, x0:x0 + cw]
        return cv2.resize(region, (panel_w, panel_h))

    top = _panel(cx_left, cy_left)
    bottom = _panel(cx_right, cy_right)
    canvas = cv2.vconcat([top, bottom])
    return canvas


# ── Decorations ─────────────────────────────────────────────────────

def _active_segment(segments: List[Dict], time: float) -> Optional[Dict]:
    """Return the transcript segment active at clip-local *time*, or None."""
    for seg in segments:
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if start <= time < end:
            return seg
    return None


def _draw_word_caption_cv(
    canvas: "np.ndarray",
    words: List[str],
    current_idx: int,
    band_y0: int,
    band_y1: int,
    style: Optional[Dict] = None,
) -> "np.ndarray":
    """Dynamic word-by-word caption with a tight background box.

    Renders a fixed block of MAX_CAPTION_WORDS words (a batch) at once —
    the whole batch appears together, then the current word is highlighted
    in the accent color (#ff914d) as the speaker goes through it one by
    one. When the speaker passes the last word, the next batch of
    MAX_CAPTION_WORDS replaces it.

    The semi-transparent background is sized to the text block itself and
    hugs it with a small padding (5px top/bottom) rather than spanning the
    whole caption band. Text never exceeds 80% of the canvas width and
    wraps onto up to two lines.
    """
    words = [w for w in words if w]
    if not words:
        return canvas
    total = len(words)
    current_idx = max(0, min(current_idx, total - 1))

    # Fixed batch: floor(current_idx / MAX_CAPTION_WORDS) * MAX_CAPTION_WORDS.
    batch_start = (current_idx // MAX_CAPTION_WORDS) * MAX_CAPTION_WORDS
    window = words[batch_start:batch_start + MAX_CAPTION_WORDS]

    font = cv2.FONT_HERSHEY_TRIPLEX
    base_scale = CAPTION_FONT_SCALE
    thick = CAPTION_FONT_THICK
    base_bgr = tuple(reversed(_parse_hex((style or {}).get("color"))))
    white = base_bgr
    accent = CAPTION_ACCENT

    # Build wrapped lines that fit within MAX_CAPTION_W.
    lines: List[List[str]] = [[]]
    line_w = 0.0
    space_w = cv2.getTextSize(" ", font, base_scale, thick)[0][0]
    for w in window:
        ww = cv2.getTextSize(w, font, base_scale, thick)[0][0]
        if lines[-1] and line_w + ww > MAX_CAPTION_W:
            lines.append([])
            line_w = 0.0
        lines[-1].append(w)
        line_w += ww + space_w

    # Measure the tight background box around the text block.
    line_h = 0
    block_w = 0
    for line in lines:
        full = " ".join(line)
        (tw, th), _ = cv2.getTextSize(full, font, base_scale, thick)
        line_h = max(line_h, th)
        block_w = max(block_w, tw)
    pad_y = 5  # background hugs the text: only 5px top/bottom
    pad_x = 20
    block_h = line_h * len(lines) + 2 * pad_y
    block_w = min(block_w + 2 * pad_x, CANVAS_W - 40)

    # Center the block horizontally; vertically center it within the band.
    x0 = (CANVAS_W - block_w) // 2
    y0 = band_y0 + (band_y1 - band_y0 - block_h) // 2

    # Draw the tight semi-transparent black background.
    overlay = np.full((block_h, block_w, 3), 0, dtype=np.uint8)
    roi = canvas[y0:y0 + block_h, x0:x0 + block_w]
    cv2.addWeighted(roi, 0.55, overlay, 0.45, 0, roi)

    # Draw words on top of the background box.
    start_y = y0 + pad_y + line_h
    word_idx = batch_start
    for line in lines:
        full = " ".join(line)
        (tw, _), _ = cv2.getTextSize(full, font, base_scale, thick)
        x = x0 + (block_w - tw) // 2
        for w in line:
            is_current = word_idx == current_idx
            color = accent if is_current else white
            cv2.putText(canvas, w, (x, start_y), font, base_scale, color, thick, cv2.LINE_AA)
            ww = cv2.getTextSize(w, font, base_scale, thick)[0][0]
            x += ww + space_w
            word_idx += 1
        start_y += line_h
    return canvas


def _draw_word_caption(
    canvas: "np.ndarray",
    words: List[str],
    current_idx: int,
    band_y0: int,
    band_y1: int,
    style: Optional[Dict] = None,
) -> "np.ndarray":
    """Word-by-word caption honoring the client's caption style preset.

    Prefers Pillow (real TTF fonts, brand colors, soft chips) and falls back
    to the OpenCV renderer when Pillow isn't installed. A fixed block of
    MAX_CAPTION_WORDS words is drawn as one sprite; the current word rides on
    an accent chip so lip-sync stays readable.
    """
    words = [w for w in words if w]
    if not words:
        return canvas
    total = len(words)
    current_idx = max(0, min(current_idx, total - 1))
    batch_start = (current_idx // MAX_CAPTION_WORDS) * MAX_CAPTION_WORDS
    window = words[batch_start:batch_start + MAX_CAPTION_WORDS]

    if _HAS_PIL:
        rgba = _word_block_rgba(window, batch_start, current_idx, style)
        block_h, block_w = rgba.shape[:2]
        x0 = max((CANVAS_W - block_w) // 2, 20)
        y0 = band_y0 + (band_y1 - band_y0 - block_h) // 2
        return _composite_rgba(canvas, rgba, x0, y0)
    return _draw_word_caption_cv(canvas, words, current_idx, band_y0, band_y1, style)


def _draw_hook_title(canvas: "np.ndarray", title: str) -> "np.ndarray":
    """Draw the hook headline inside the top safe zone (y ~150px)."""
    if not title:
        return canvas
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 1.0
    thick = 2
    (tw, th), _ = cv2.getTextSize(title, font, scale, thick)
    while tw > MAX_CAPTION_W and scale > 0.5:
        scale -= 0.05
        (tw, th), _ = cv2.getTextSize(title, font, scale, thick)
    x = (CANVAS_W - tw) // 2
    y = TOP_SAFE_H // 2 + th // 2
    cv2.putText(canvas, title, (x, y), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return canvas


def _draw_divider(canvas: "np.ndarray", layout_type: str) -> "np.ndarray":
    """2px accent divider line for the podcast split at y ~960px."""
    if layout_type != "split_vertical":
        return canvas
    y = CANVAS_H // 2  # 960
    cv2.line(canvas, (0, y - 1), (CANVAS_W, y - 1), (200, 200, 200), 2)
    return canvas


def _draw_branding(canvas: "np.ndarray", branding: Optional[Dict]) -> "np.ndarray":
    """Bottom-corner branding: client logo thumbnail + lower-third line.

    The logo is alpha-composited at bottom-right inside the safe zone; the
    lower-third text sits bottom-left so the two never overlap. All failures
    are swallowed — branding is decorative and must never break a render.
    """
    if not branding:
        return canvas
    if not _HAS_PIL:
        return canvas

    logo = branding.get("logo")
    lower = (branding.get("lower_third") or "").strip()

    if lower:
        try:
            font = _resolve_font("inter", 44)
            probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
            tw = probe.textlength(lower, font=font)
            pad_x, pad_y = 24, 14
            bw = int(tw) + 2 * pad_x
            bh = 44 + 2 * pad_y
            img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=12, fill=(0, 0, 0, 190))
            d.text((pad_x, pad_y), lower, font=font, fill=(240, 239, 233, 255))
            arr = np.array(img)
            _composite_rgba(canvas, arr, 40, CANVAS_H - bh - 80)
        except Exception:
            pass

    if logo:
        try:
            img = Image.open(logo).convert("RGBA")
            img.thumbnail((220, 60), Image.LANCZOS)
            arr = np.array(img)
            h, w = arr.shape[:2]
            _composite_rgba(canvas, arr, CANVAS_W - w - 40, CANVAS_H - h - 80)
        except Exception:
            pass

    return canvas


def _decorate_frame(
    frame: "np.ndarray",
    spec: Dict[str, Any],
    frame_idx: int,
    total_frames: int,
    progress: float,
    time: float = 0.0,
    segments: Optional[List[Dict]] = None,
    style: Optional[Dict] = None,
    branding: Optional[Dict] = None,
) -> "np.ndarray":
    """Apply canvas-safe zones, word-by-word captions, hook title, divider,
    color overlay, and widgets to a 1080x1920 frame.

    When *segments* (clip-local transcript segments with start/end/text) are
    provided, the active segment's text is shown as a word-by-word caption
    synced to the audio. Otherwise the static hook *text* is revealed across
    the clip progress.
    """
    out = frame
    layout_type = spec.get("layout", {}).get("type", "single_focus")
    typo = spec.get("typography") or {}

    # Color overlay
    overlay_color = spec.get("layout", {}).get("color_overlay")
    if overlay_color is not None and len(overlay_color) == 4:
        r, g, b = overlay_color[0], overlay_color[1], overlay_color[2]
        alpha = overlay_color[3]
        tint = np.full_like(out, [b, g, r], dtype=np.uint8)
        out = cv2.addWeighted(out, 1.0 - alpha, tint, alpha, 0)

    # Divider line (podcast split)
    out = _draw_divider(out, layout_type)

    # Hook title in the top safe zone (stage layout)
    title = typo.get("title", "")
    if layout_type == "single_focus" and title:
        out = _draw_hook_title(out, title)

    # Word-by-word captions (real transcript segments when available)
    text = typo.get("text", "")
    pos = style.get("position") if style else None
    if segments:
        band_y0, band_y1 = _band_for_position(pos, layout_type)
        seg = _active_segment(segments, time)
        if seg is not None:
            seg_words = seg.get("words") or []
            if seg_words:
                words = [str(w.get("word", "")).strip() for w in seg_words]
                current_idx = 0
                for i, w in enumerate(seg_words):
                    if float(w.get("start", 0.0)) <= time:
                        current_idx = i
                current_idx = min(current_idx, len(words) - 1)
            else:
                words = str(seg.get("text", "")).strip().split()
                seg_dur = max(float(seg.get("end", 0.0)) - float(seg.get("start", 0.0)), 0.0001)
                seg_progress = min(max((time - float(seg.get("start", 0.0))) / seg_dur, 0.0), 1.0)
                shown = max(1, int(seg_progress * len(words))) if words else 0
                current_idx = min(shown - 1, len(words) - 1)
            out = _draw_word_caption(out, words, current_idx, band_y0, band_y1, style)
    elif text:
        if layout_type == "split_vertical":
            if pos == "lower_third":
                band_y0, band_y1 = 1500, 1700          # Option B: lower-third
            else:
                band_y0, band_y1 = 860, 1060           # Option A: center divider
        else:
            band_y0, band_y1 = _band_for_position(pos, layout_type)
        words = text.split()
        shown = max(1, int(progress * len(words))) if words else 0
        current_idx = min(shown - 1, len(words) - 1)
        out = _draw_word_caption(out, words, current_idx, band_y0, band_y1, style)

    # Branding overlay (logo + lower-third line) in the bottom corner
    out = _draw_branding(out, branding)

    # Widgets
    widgets = spec.get("widgets", [])
    for wgt in widgets:
        if wgt.get("type") == "progress_bar":
            h, w = out.shape[:2]
            bar_w = int(w * 0.7)
            bar_h = 6
            bar_x = (w - bar_w) // 2
            bar_y = h - 40
            color = tuple(reversed(wgt.get("color", [0, 255, 102])))
            cv2.rectangle(out, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (64, 64, 64), -1)
            fill_w = int(bar_w * min(progress, 1.0))
            cv2.rectangle(out, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), color, -1)

    return out


# ── Generic compose engine ──────────────────────────────────────────

def _reframe_composed(
    in_path: str,
    out_path: str,
    spec: Dict[str, Any],
    source_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    progress: Optional[Progress] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    segments: Optional[List[Dict]] = None,
    style: Optional[Dict] = None,
    branding: Optional[Dict] = None,
) -> str:
    """Two-pass render: pre-scan scene + smooth trajectory, then render.

    Pass 1 samples the video at low FPS to detect face positions, builds
    a smooth camera trajectory (median filter + EMA + smoothstep interp),
    and decides whether padded-blur fallback is needed.

    Pass 2 renders every frame using the pre-computed trajectory — no
    per-frame face detection, zero jitter.
    """
    _open_cv()

    temp_path, orig_path = _opencv_temp(in_path)
    cap = cv2.VideoCapture(temp_path)
    if not cap.isOpened():
        if temp_path != orig_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise RuntimeError(f"could not open {in_path}")

    src_w, src_h, fps, total_frames = _get_frame_info(cap, progress)
    crop_w, crop_h = _crop_dims(src_w, src_h)

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    # ── Pass 1: pre-scan face trajectory ──
    auto_framing = spec.get("auto_framing", True)
    layout_type = spec.get("layout", {}).get("type", "single_focus")
    layout_spec = spec.get("layout", {})

    trajectory: Optional[List[Tuple[int, int]]] = None
    traj_left: Optional[List[Tuple[int, int]]] = None
    traj_right: Optional[List[Tuple[int, int]]] = None
    use_blur = False
    if auto_framing:
        print("  [pre-scan] sampling face positions...", flush=True)
        if layout_type == "split_vertical":
            traj_left, traj_right = _pre_scan_trajectory_pair(cap, src_w, src_h, total_frames, fps, face_cascade)
        else:
            trajectory, use_blur = _pre_scan_trajectory(cap, src_w, src_h, total_frames, fps, face_cascade)
        cap.release()
        cap = cv2.VideoCapture(temp_path)  # re-open for render pass

    if text or title:
        spec = {**spec}
        typo = dict(spec.get("typography") or {})
        if text:
            typo["text"] = text
        if title:
            typo["title"] = title
        spec["typography"] = typo

    # ── Pass 2: render ──
    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_w, out_h = CANVAS_W, CANVAS_H

    writer = cv2.VideoWriter(silent_path, fourcc, fps, (out_w, out_h))

    frame_idx = 0
    default_cx, default_cy = src_w // 2, src_h // 2
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        if layout_type == "split_vertical":
            if traj_left is not None and traj_right is not None:
                cx_l, cy_l = traj_left[frame_idx - 1] if frame_idx - 1 < len(traj_left) else (default_cx, default_cy)
                cx_r, cy_r = traj_right[frame_idx - 1] if frame_idx - 1 < len(traj_right) else (default_cx, default_cy)
            else:
                cx_l, cy_l = src_w // 4, src_h // 2
                cx_r, cy_r = src_w * 3 // 4, src_h // 2
            composed = _render_podcast_canvas(frame, src_w, src_h, cx_l, cy_l, cx_r, cy_r)
        elif use_blur:
            composed = _render_contain(frame, out_w, out_h, bg_style="blur")
        elif trajectory is not None:
            cx, cy = trajectory[frame_idx - 1] if frame_idx - 1 < len(trajectory) else (default_cx, default_cy)
            composed = _render_stage_canvas(frame, src_w, src_h, cx, cy)
        else:
            composed = _render_stage_canvas(frame, src_w, src_h, default_cx, default_cy)

        pct = frame_idx / total_frames if total_frames > 0 else 0
        clip_time = frame_idx / fps if fps > 0 else 0.0
        composed = _decorate_frame(composed, spec, frame_idx, total_frames, pct, time=clip_time, segments=segments, style=style, branding=branding)
        writer.write(composed)

        if progress is not None and (frame_idx % 30 == 0 or total_frames == 0):
            progress.update(frame_idx)

    cap.release()
    writer.release()
    del cap, writer
    gc.collect()

    _mux_audio(silent_path, out_path, source_path, start_time, end_time, in_path)
    os.remove(silent_path)
    _cleanup_temp(temp_path, orig_path)
    return out_path


# ── Template dispatch ───────────────────────────────────────────────

REFRAME_FN: Dict[str, Callable[..., str]] = {}

# Templates requiring the compose engine are handled by _reframe_composed
# via the wrapper below.
_COMPOSE_TEMPLATES: Dict[str, Dict[str, Any]] = {}


def _register_templates() -> None:
    """Idempotently register all TEMPLATE_SPECS that use the compose engine."""
    if _COMPOSE_TEMPLATES:
        return
    for tid, spec in TEMPLATE_SPECS.items():
        _COMPOSE_TEMPLATES[tid] = spec


def resolve_template(template: Optional[str]) -> str:
    """Normalise a template name; return the default if unknown."""
    if template and template.lower() in TEMPLATE_SPECS:
        return template.lower()
    return DEFAULT_TEMPLATE


# ── Public API ──────────────────────────────────────────────────────

def crop_clip_local(
    source_path: str,
    start_time: float,
    end_time: float,
    out_path: str,
    template: Optional[str] = None,
    progress: Optional[Progress] = None,
    text: Optional[str] = None,
    title: Optional[str] = None,
    segments: Optional[List[Dict]] = None,
    burn_captions: bool = False,
    caption_style: Optional[Dict] = None,
    branding: Optional[Dict] = None,
) -> str:
    """Cut + reframe one highlight to 9:16, returning the local mp4 path.

    *template* selects the cropping/composition strategy (see TEMPLATE_SPECS).
    Defaults to *stage_solo_speaker*.
    *text* is the word-by-word caption (hook line) burned into the canvas.
    *title* is the hook headline shown in the top safe zone.
    *segments* are clip-local transcript segments (start/end/text, offset so
    the clip begins at t=0). When provided, real captions synced to the
    audio replace the static *text* fallback.
    *burn_captions* is off by default: captions are added as layers in the
    FreeCut editor and baked in at export time, so nothing is double-burned.
    Set it to True to render *text*/*segments* into the frame pixels here.
    """
    if not burn_captions:
        # Clean output: leave the captions to the editor's timeline layers.
        text = None
        segments = None
    template = resolve_template(template)
    _register_templates()

    cut_path = out_path + ".cut.mp4"
    try:
        _cut_subclip(source_path, start_time, end_time, cut_path)

        if template in REFRAME_FN:
            reframe_fn = REFRAME_FN[template]
            reframe_fn(
                cut_path,
                out_path,
                source_path=source_path,
                start_time=start_time,
                end_time=end_time,
                progress=progress,
            )
        else:
            spec = TEMPLATE_SPECS[template]
            _reframe_composed(
                cut_path,
                out_path,
                spec=spec,
                source_path=source_path,
                start_time=start_time,
                end_time=end_time,
                progress=progress,
                text=text,
                title=title,
                segments=segments,
                style=caption_style,
                branding=branding,
            )
    finally:
        if os.path.exists(cut_path):
            for _ in range(30):
                try:
                    os.remove(cut_path)
                    break
                except PermissionError:
                    time.sleep(0.2)
    return out_path


def _clip_local_segments(transcript: Dict, start_time: float, end_time: float) -> List[Dict]:
    """Map source-time transcript segments to clip-local time for [start, end].

    Only segments overlapping the highlight are kept; each is offset so the
    clip begins at t=0 and clamped to the clip's duration. Word-level
    timestamps (if present) are offset the same way so captions stay in sync.
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
                "start": max(0.0, ws - start_time),
                "end": min(clip_duration, we - start_time),
                "word": w.get("word", ""),
            })
        out.append({
            "start": max(0.0, s - start_time),
            "end": min(clip_duration, e - start_time),
            "text": seg.get("text", ""),
            "words": words,
        })
    return out


def crop_highlights_local(
    source_path: str,
    highlights: List[Dict],
    out_dir: Optional[str] = None,
    template: Optional[str] = None,
    transcript: Optional[Dict] = None,
    burn_captions: bool = False,
    caption_style: Optional[Dict] = None,
    branding: Optional[Dict] = None,
) -> List[Dict]:
    """Crop every highlight to 9:16 vertical, writing to out_dir.

    *template* is passed through to *crop_clip_local*.
    *transcript* (optional) provides segment timestamps for real, audio-synced
    captions burned into each clip.
    *burn_captions* defaults to False — captions are styled in the FreeCut
    editor and baked at export time instead of into the rendered pixels.
    """
    template = resolve_template(template)
    out_dir = out_dir or LOCAL_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict] = []
    total = len(highlights)
    label = TEMPLATE_LABELS.get(template, template)
    with Progress(f"Rendering {total} vertical shorts ({label})", total=total) as outer:
        for i, h in enumerate(highlights, 1):
            out_path = os.path.join(out_dir, f"short_{i:02d}.mp4")
            print(f"\n[clip/local] {i}/{total}: {h.get('title', '(untitled)')}", flush=True)
            try:
                segments = _clip_local_segments(transcript, float(h["start_time"]), float(h["end_time"])) if transcript and burn_captions else None
                with Progress(f"  Clip {i}/{total}", total=None) as p:
                    crop_clip_local(
                        source_path,
                        float(h["start_time"]),
                        float(h["end_time"]),
                        out_path,
                        template=template,
                        progress=p,
                        text=h.get("hook_sentence") or h.get("title") if burn_captions else None,
                        title=h.get("title"),
                        segments=segments,
                        burn_captions=burn_captions,
                        caption_style=caption_style,
                        branding=branding,
                    )
                results.append({**h, "clip_url": out_path})
            except Exception as e:
                print(f"[clip/local] {i} failed: {e}", flush=True)
                results.append({**h, "clip_url": None, "error": str(e)})
            outer.update(i)
    return results

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
import re
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
MAX_CAPTION_WORDS = 3                   # words shown per caption burst (fast-paced kinetic standard)
CAPTION_FONT_SCALE = 2.2                # large bold word-by-word caption font
CAPTION_FONT_THICK = 4                  # bold stroke for captions
CAPTION_ACCENT = (0, 234, 255)          # #FFEA00 Electric Yellow in BGR — active word highlight


# ── Caption style support (Pillow TTF rendering) ──────────────────────
# High-impact display typography (Hormozi / Submagic kinetic standard).
# Outer outline (stroke) + drop shadow + neon word highlight ensures 100%
# legibility on any footage without requiring an ugly gray bounding box.

_FONT_TOKEN_FILES = {
    "impact": ["impact.ttf", "ariblk.ttf", "seguibl.ttf", "segoeuib.ttf"],
    "heavy": ["ariblk.ttf", "seguibl.ttf", "impact.ttf", "arialbd.ttf"],
    "inter": ["segoeuib.ttf", "seguibl.ttf", "arialbd.ttf", "arial.ttf"],
    "serif": ["georgiab.ttf", "georgia.ttf", "timesbd.ttf", "times.ttf"],
    "mono": ["consolab.ttf", "consola.ttf", "courbd.ttf", "cour.ttf"],
}
_WINDOWS_FONT_DIR = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"

_font_cache: Dict[Tuple[str, int], Any] = {}

# Contextual high-impact emojis mapped to spoken keywords
EMOJI_KEYWORDS: Dict[str, str] = {
    "money": "💰", "cash": "💵", "dollar": "💵", "dollars": "💵", "rich": "🤑", "wealth": "💰",
    "secret": "🤫", "truth": "🤫", "nobody": "🤫", "quiet": "🤫",
    "fire": "🔥", "crazy": "🔥", "insane": "🔥", "epic": "🔥", "hot": "🔥",
    "mistake": "❌", "wrong": "❌", "never": "🚫", "stop": "🛑", "no": "🚫", "fail": "❌",
    "win": "🏆", "winning": "🏆", "success": "🏆", "first": "🥇", "best": "⭐", "top": "🔝",
    "growth": "📈", "grow": "📈", "scale": "🚀", "startup": "🚀", "rocket": "🚀", "fast": "⚡",
    "mind": "🧠", "brain": "🧠", "think": "💡", "idea": "💡", "learn": "📚",
    "heart": "❤️", "love": "❤️", "shock": "⚡", "power": "⚡", "boom": "💥",
    "danger": "⚠️", "warning": "⚠️", "kill": "💀", "dead": "💀", "death": "💀",
}


def _resolve_font(token: str, size: int):
    key = (token or "impact", size)
    if key in _font_cache:
        return _font_cache[key]
    for name in _FONT_TOKEN_FILES.get(token or "impact", _FONT_TOKEN_FILES["impact"]):
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


def _resolve_emoji_font(size: int = 76):
    key = ("emoji", size)
    if key in _font_cache:
        return _font_cache[key]
    cand = _WINDOWS_FONT_DIR / "seguiemj.ttf"
    if cand.exists():
        try:
            font = ImageFont.truetype(str(cand), size)
            _font_cache[key] = font
            return font
        except Exception:
            pass
    return None


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


SUBTITLE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "hormozi_pop": {
        "label": "Hormozi Viral Pop (Impact, 1.22x Word Pop, Emojis)",
        "font": "impact",
        "default_color": "#FFEA00",  # Electric Yellow highlight
        "pop_scale": 1.22,           # Active word expands by 22%
        "stroke_width": 10,
        "shadow_offset": (4, 6),
        "uppercase": True,
        "emojis": True,
        "boxed": False,
    },
    "beast_neon": {
        "label": "MrBeast Dynamic (Heavy Sans, Neon Cyan, Bold Stroke)",
        "font": "heavy",
        "default_color": "#00F0FF",  # Neon Cyan highlight
        "pop_scale": 1.14,           # Active word expands by 14%
        "stroke_width": 12,
        "shadow_offset": (5, 8),
        "uppercase": True,
        "emojis": True,
        "boxed": False,
    },
    "minimal_clean": {
        "label": "Clean Minimalist / Ali Abdaal (Inter Sans, Soft Coral)",
        "font": "inter",
        "default_color": "#F4A261",  # Warm Coral highlight
        "pop_scale": 1.05,
        "stroke_width": 5,
        "shadow_offset": (3, 4),
        "uppercase": False,
        "emojis": False,
        "boxed": False,
    },
    "documentary": {
        "label": "Vox / Documentary (Georgia Serif, Editorial Red)",
        "font": "serif",
        "default_color": "#E63946",  # Editorial Crimson highlight
        "pop_scale": 1.0,            # Flat, elegant reading cadence
        "stroke_width": 6,
        "shadow_offset": (3, 4),
        "uppercase": False,
        "emojis": False,
        "boxed": False,
    },
    "cyber_terminal": {
        "label": "Cyber Tech (JetBrains Mono, Terminal Green)",
        "font": "mono",
        "default_color": "#00FF66",  # Matrix / Cyber Green highlight
        "pop_scale": 1.15,
        "stroke_width": 8,
        "shadow_offset": (4, 4),
        "uppercase": True,
        "emojis": False,
        "boxed": False,
    },
}


def _word_block_rgba(
    window: List[str],
    batch_start: int,
    current_idx: int,
    style: Optional[Dict],
) -> "np.ndarray":
    """Rasterize a modern kinetic caption block (1-3 words) with stroke & shadow.

    Supports company-specific subtitle templates with:
    - White base color for inactive words.
    - Custom/template accent color for the active word being said.
    - Hormozi font size pop effect (active word physically expands by ~22% on baseline).
    - Optional contextual emojis.
    """
    tmpl_id = (style or {}).get("caption_template") or "hormozi_pop"
    tmpl = SUBTITLE_TEMPLATES.get(tmpl_id, SUBTITLE_TEMPLATES["hormozi_pop"])

    # Base color for inactive words is always crisp high-contrast White
    base_rgb = (255, 255, 255)

    # Active word highlight color: user-configured color from project settings
    # or the template default accent
    custom_color = (style or {}).get("color")
    if custom_color and custom_color.strip().upper() not in ("#FFFFFF", "#FFF", "WHITE"):
        accent_rgb = _parse_hex(custom_color)
    else:
        accent_rgb = _parse_hex(tmpl.get("default_color", "#FFEA00"))

    font_token = (style or {}).get("font") or tmpl.get("font", "impact")
    base_size = 90
    pop_scale = float(tmpl.get("pop_scale", 1.20))
    pop_size = int(base_size * pop_scale) if pop_scale > 1.0 else base_size
    font_base = _resolve_font(font_token, base_size)
    font_pop = _resolve_font(font_token, pop_size)

    def _font_metrics(f):
        try:
            return f.getmetrics()
        except Exception:
            return int(f.size * 0.8), int(f.size * 0.2)

    # Safe width constraint: captions must never exceed 80% of canvas width (864px),
    # guaranteeing at least 108px safe margins on both left and right edges.
    SAFE_CAPTION_W = int(CANVAS_W * 0.80)  # 864px
    pad_x = 36
    pad_y = 26
    avail_w = SAFE_CAPTION_W - 2 * pad_x

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # Casing
    if tmpl.get("uppercase", True):
        disp_words = [w.upper() for w in window]
    else:
        disp_words = window

    # Check for contextual emoji on active word
    active_emoji = None
    if tmpl.get("emojis", True):
        for idx_w, w in enumerate(window):
            abs_i = batch_start + idx_w
            clean_w = re.sub(r"[^a-zA-Z]", "", w).lower()
            if abs_i == current_idx and clean_w in EMOJI_KEYWORDS:
                active_emoji = EMOJI_KEYWORDS[clean_w]
                break

    # Auto-fit shrink loop: dynamically downscale font if words are long so captions NEVER clip
    space_w = probe.textlength(" ", font=font_base) + 10
    while base_size > 36:
        word_widths: List[float] = []
        word_fonts: List[Any] = []
        for idx_w, w in enumerate(disp_words):
            abs_i = batch_start + idx_w
            is_active = (abs_i == current_idx)
            w_font = font_pop if is_active else font_base
            word_fonts.append(w_font)
            word_widths.append(probe.textlength(w, font=w_font))

        emoji_font = _resolve_emoji_font(int(pop_size * 0.80)) if (active_emoji and tmpl.get("emojis", True)) else None
        emoji_w = (probe.textlength(active_emoji, font=emoji_font) + 16) if (active_emoji and emoji_font) else 0
        total_text_w = sum(word_widths) + max(0, len(disp_words) - 1) * space_w
        total_w = int(total_text_w + emoji_w)

        if total_w <= avail_w:
            break

        fit_scale = min(0.94, avail_w / max(1, total_w))
        base_size = max(36, int(base_size * fit_scale))
        pop_size = int(base_size * pop_scale) if pop_scale > 1.0 else base_size
        font_base = _resolve_font(font_token, base_size)
        font_pop = _resolve_font(font_token, pop_size)
        space_w = probe.textlength(" ", font=font_base) + 8

    ascent_base, descent_base = _font_metrics(font_base)
    ascent_pop, descent_pop = _font_metrics(font_pop)
    max_ascent = max(ascent_base, ascent_pop)
    max_descent = max(descent_base, descent_pop)
    line_h = max_ascent + max_descent

    block_w = min(total_w + 2 * pad_x, SAFE_CAPTION_W)
    block_h = line_h + 2 * pad_y

    img = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if (style or {}).get("boxed", tmpl.get("boxed", False)):
        d.rounded_rectangle([10, 10, block_w - 10, block_h - 10], radius=16, fill=(0, 0, 0, 160))

    baseline_y = pad_y + max_ascent
    cur_x = pad_x
    stroke_w = tmpl.get("stroke_width", 10)
    shadow_dx, shadow_dy = tmpl.get("shadow_offset", (4, 6))

    for idx_w, w in enumerate(disp_words):
        abs_i = batch_start + idx_w
        is_active = (abs_i == current_idx)
        w_font = word_fonts[idx_w]
        w_ascent, _ = _font_metrics(w_font)
        word_y = baseline_y - w_ascent

        text_color = accent_rgb if is_active else base_rgb
        cur_stroke = stroke_w + (2 if is_active else 0)

        # 1. Drop shadow pass
        d.text(
            (cur_x + shadow_dx, word_y + shadow_dy),
            w,
            font=w_font,
            fill=(0, 0, 0, 160),
            stroke_width=cur_stroke,
            stroke_fill=(0, 0, 0, 160),
        )

        # 2. Main text with crisp black outline
        d.text(
            (cur_x, word_y),
            w,
            font=w_font,
            fill=text_color + (255,),
            stroke_width=cur_stroke,
            stroke_fill=(0, 0, 0, 255),
        )

        cur_x += int(word_widths[idx_w] + space_w)

    # Draw emoji if present
    if active_emoji and emoji_font:
        emoji_ascent, _ = _font_metrics(emoji_font)
        emoji_x = cur_x - int(space_w) + 12
        emoji_y = baseline_y - emoji_ascent - 4
        try:
            d.text((emoji_x, emoji_y), active_emoji, font=emoji_font, embedded_color=True)
        except Exception:
            d.text((emoji_x, emoji_y), active_emoji, font=emoji_font, fill=(255, 255, 255, 255))

    return np.array(img)


def _band_for_position(
    position: Optional[str],
    layout_type: str,
    is_solo: bool = False,
) -> Tuple[int, int]:
    """Calculate the vertical safe band (y0, y1) for subtitles on a 1080x1920 canvas.

    Podcast Split Screen rules:
    - Dual split screen view (not is_solo): Subtitles sit right at the center seam
      where the top and bottom clips meet (midpoint y = 960px, band 860..1060px).
    - Dynamic solo full-screen cut (is_solo = True): Subtitles automatically move
      to the bottom half (band 1400..1660px) to prevent covering the speaker's face.
    """
    if layout_type == "split_vertical":
        if is_solo:
            # Full vertical solo view: shift to bottom half so face & chin stay clear
            if position == "top":
                return 320, 620
            return 1400, 1660

        # Dual split view: right at the center meeting line (y = 960)
        if position == "top":
            return 320, 620
        # By default (and for center/lower_third), center right on the meeting seam:
        return 860, 1060

    if position == "top":
        return 320, 620
    if position == "center":
        return 720, 1300
    return CAPTION_BAND_TOP, CAPTION_BAND_BOTTOM


# ── Template specs (from template.json) ─────────────────────────────

# Each spec describes a layout type and optional stylings that the reframe
# function reads at render time.

TEMPLATE_SPECS: Dict[str, Dict[str, Any]] = {
    "full_bleed_solo": {
        "label": "Full Bleed (Solo Speaker)",
        "category": "Talk & Conversation",
        "layout": {"type": "full_bleed"},
        "typography": {"position": "lower_third", "font_scale": 1.1},
        "auto_framing": True,
        "video_filter": "vivid_pop",
    },
    "blurred_backdrop": {
        "label": "Blurred Backdrop (Context / Wide)",
        "category": "Presentation & Wide",
        "layout": {"type": "blurred_backdrop"},
        "typography": {"position": "lower_third", "font_scale": 1.1},
        "auto_framing": True,
        "video_filter": "vivid_pop",
    },
    "stage_solo_speaker": {
        "label": "Stage & Solo Speaker",
        "category": "Talk & Conversation",
        "layout": {"type": "single_focus"},
        "typography": {"position": "lower_third", "font_scale": 1.1},
        "auto_framing": True,
        "video_filter": "vivid_pop",
    },
    "podcast_split_screen": {
        "label": "Podcast & Dialogue",
        "category": "Talk & Conversation",
        "layout": {"type": "split_vertical", "split_ratio": 0.5, "focus": "top"},
        "typography": {"position": "lower_third", "max_lines": 2},
        "auto_framing": True,
        "solo_switch": True,
        "bust_scale": 0.82,
        "video_filter": "vivid_pop",
    },
}

TEMPLATE_LABELS: Dict[str, str] = {k: v["label"] for k, v in TEMPLATE_SPECS.items()}

DEFAULT_TEMPLATE = "full_bleed_solo"


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
    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start:.3f}",
        "-i", source_path,
        "-t", f"{duration:.3f}",
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
    master_audio: bool = True,
) -> None:
    """Mux audio from the original source onto the silent reframed video,
    applying broadcast vocal mastering and -14 LUFS loudness normalization.
    """
    if source_path is not None and start_time is not None and end_time is not None:
        duration = end_time - start_time
        audio_args = [
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", source_path,
        ]
    else:
        audio_args = ["-i", in_path] if in_path else []

    audio_filters: List[str] = []
    if master_audio and audio_args:
        # Agency-grade broadcast vocal chain:
        # 1. 80Hz highpass: eliminates mic plosives, room rumble, and desk thumps
        # 2. 3kHz presence EQ (+2dB, Q=1.0): boosts speech clarity on smartphone speakers
        # 3. loudnorm: normalizes to -14 LUFS (Shorts/Reels target) with -1.5 dBTP true peak ceiling
        audio_filters = [
            "-af",
            "highpass=f=80,equalizer=f=3000:t=q:w=1:g=2,loudnorm=I=-14:LRA=7:TP=-1.5",
        ]

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", silent_path,
        *audio_args,
        # Re-encode to H.264: OpenCV writes MPEG-4 Part 2 (mp4v), which
        # browsers cannot decode — the video track silently disappears.
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        *audio_filters,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
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
        if hasattr(progress, "set_total"):
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
        if progress is not None:
            if getattr(progress, "is_cancelled", False) or (callable(getattr(progress, "check_cancelled", None)) and progress.check_cancelled()):
                cap.release()
                writer.release()
                if os.path.exists(silent_path):
                    try:
                        os.remove(silent_path)
                    except Exception:
                        pass
                _cleanup_temp(temp_path, orig_path)
                raise InterruptedError("Render cancelled by user.")
            if (frame_idx % 30 == 0 or total_frames == 0) and hasattr(progress, "update"):
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
        if progress is not None:
            if getattr(progress, "is_cancelled", False) or (callable(getattr(progress, "check_cancelled", None)) and progress.check_cancelled()):
                cap.release()
                writer.release()
                if os.path.exists(silent_path):
                    try:
                        os.remove(silent_path)
                    except Exception:
                        pass
                _cleanup_temp(temp_path, orig_path)
                raise InterruptedError("Render cancelled by user.")
            if (frame_idx % 30 == 0 or total_frames == 0) and hasattr(progress, "update"):
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


def _detect_all_faces(
    gray: "np.ndarray",
    src_w: int,
    src_h: int,
    face_cascade: "cv2.CascadeClassifier",
    profile_cascade: Optional["cv2.CascadeClassifier"] = None,
    upperbody_cascade: Optional["cv2.CascadeClassifier"] = None,
) -> List[Tuple[int, int, int, int]]:
    """Detect faces across frontal, profile, and upper-body angles.

    Filters out detections in the lower 35% of the frame (hands, belts, microphones)
    and sorts by box area (largest foreground face first). If faces are turned
    or blocked by microphones, upper-body detection estimates head position.
    """
    f_boxes = list(face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)))
    p_boxes: List[Any] = []
    p_flip_adj: List[Any] = []

    if profile_cascade is not None:
        p_boxes = list(profile_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)))
        gray_flip = cv2.flip(gray, 1)
        p_flip = list(profile_cascade.detectMultiScale(gray_flip, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)))
        p_flip_adj = [[src_w - (x + w), y, w, h] for (x, y, w, h) in p_flip]

    all_boxes = [b for b in f_boxes + p_boxes + p_flip_adj if b[1] < src_h * 0.65]

    # Upper-body fallback: if face is obscured by microphone or tilted downward
    if not all_boxes and upperbody_cascade is not None:
        ub_boxes = list(upperbody_cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=3, minSize=(80, 80)))
        for ub_x, ub_y, ub_w, ub_h in ub_boxes:
            if ub_y < src_h * 0.70:
                head_w = int(ub_w * 0.45)
                head_h = int(ub_h * 0.40)
                head_x = max(0, ub_x + (ub_w - head_w) // 2)
                head_y = max(0, ub_y - int(head_h * 0.45))
                all_boxes.append((head_x, head_y, head_w, head_h))

    return sorted(all_boxes, key=lambda b: b[2] * b[3], reverse=True)


def _pre_scan_samples_single(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
    profile_cascade: Optional["cv2.CascadeClassifier"] = None,
    upperbody_cascade: Optional["cv2.CascadeClassifier"] = None,
) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Pass 1 (Single Focus): Coarse Discovery pre-scan sampling."""
    sample_every = max(1, int(fps / _PRE_SCAN_FPS))
    samples: List[Dict[str, Any]] = []
    prev_small: Optional["np.ndarray"] = None
    union_widths: List[int] = []

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (160, 90))
            is_cut = False
            if prev_small is not None:
                diff = float(np.mean(cv2.absdiff(small, prev_small)))
                if diff > 28.0:
                    is_cut = True
            else:
                is_cut = True
            prev_small = small

            faces = _detect_all_faces(gray, src_w, src_h, face_cascade, profile_cascade, upperbody_cascade)
            u_cx = u_cy = None
            u_w = 0
            if faces:
                xs = [f[0] for f in faces]
                ys = [f[1] for f in faces]
                xe = [f[0] + f[2] for f in faces]
                ye = [f[1] + f[3] for f in faces]
                u_cx = (min(xs) + max(xe)) // 2
                u_cy = (min(ys) + max(ye)) // 2
                u_w = max(xe) - min(xs)
                union_widths.append(u_w)

            samples.append({
                "frame_idx": frame_idx,
                "is_cut": is_cut,
                "cx": u_cx,
                "cy": u_cy,
                "faces_count": len(faces),
            })
        frame_idx += 1

    return samples, union_widths


def _refine_cut_frame(
    cap: "cv2.VideoCapture",
    f_start: int,
    f_end: int,
    threshold: float = 25.0,
) -> int:
    """Refine a coarse scene cut between f_start and f_end to the exact frame.

    Scans downscaled grayscale thumbnails (80x45) frame-by-frame between f_start and f_end.
    Returns the exact frame index where consecutive frame difference is maximized.
    If no difference exceeds threshold, returns f_end.
    """
    if f_end <= f_start + 1:
        return f_end

    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, f_start))
    prev_small: Optional["np.ndarray"] = None
    max_diff = 0.0
    best_f = f_end

    for fi in range(f_start, f_end + 1):
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (80, 45))
        if prev_small is not None:
            diff = float(np.mean(cv2.absdiff(small, prev_small)))
            if diff > max_diff and diff >= threshold:
                max_diff = diff
                best_f = fi
        prev_small = small

    return best_f


def _audit_and_refine_trajectory(
    samples: List[Dict[str, Any]],
    union_widths: List[int],
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    crop_w: int,
    cap: Optional["cv2.VideoCapture"] = None,
) -> Tuple[List[Tuple[int, int]], bool]:
    """Pass 2 (Single Focus): Imperfection Audit & Refinement Pass.

    Audits shot boundaries, merges false-positive micro-shots (<1.2s), clamps
    vertical headroom to the safe zone, and locks framing anchors with zero jitter.
    """
    default_head_y = int(src_h * 0.28)
    median_union_w = int(np.median(union_widths)) if union_widths else 0
    use_blur = median_union_w > crop_w * 0.8

    # Partition raw samples into shots
    raw_shots: List[List[Dict[str, Any]]] = []
    current_shot: List[Dict[str, Any]] = []
    for s in samples:
        if s["is_cut"] and current_shot:
            raw_shots.append(current_shot)
            current_shot = []
        current_shot.append(s)
    if current_shot:
        raw_shots.append(current_shot)

    # Imperfection 1: Merge false micro-shots (<1.2s)
    min_shot_samples = max(2, int(1.2 * _PRE_SCAN_FPS))
    merged_shots: List[List[Dict[str, Any]]] = []
    for shot in raw_shots:
        if merged_shots and len(shot) < min_shot_samples:
            prev = merged_shots[-1]
            prev_cx = [s["cx"] for s in prev if s["cx"] is not None]
            cur_cx = [s["cx"] for s in shot if s["cx"] is not None]
            if prev_cx and cur_cx and abs(np.median(cur_cx) - np.median(prev_cx)) < (src_w * 0.08):
                merged_shots[-1].extend(shot)
                continue
        merged_shots.append(shot)

    # Refine cut boundaries to exact frame
    if cap is not None and len(merged_shots) > 1:
        for idx in range(len(merged_shots) - 1):
            f_prev = merged_shots[idx][-1]["frame_idx"]
            f_curr = merged_shots[idx + 1][0]["frame_idx"]
            exact_f = _refine_cut_frame(cap, f_prev, f_curr)
            merged_shots[idx + 1][0]["frame_idx"] = exact_f

    # Imperfection 2: Clamped locked anchors per shot
    last_anchor = (src_w // 2, default_head_y)
    shot_anchors: List[Tuple[Tuple[int, int], int, int]] = []
    min_head_y = int(src_h * 0.15)
    max_head_y = int(src_h * 0.45)

    for idx, shot in enumerate(merged_shots):
        valid_cxs = [s["cx"] for s in shot if s["cx"] is not None]
        valid_cys = [s["cy"] for s in shot if s["cy"] is not None]
        if valid_cxs and valid_cys:
            ax = int(np.median(valid_cxs))
            ay = max(min_head_y, min(max_head_y, int(np.median(valid_cys))))
            anchor = (ax, ay)
            last_anchor = anchor
        else:
            anchor = last_anchor
        start_f = shot[0]["frame_idx"]
        next_start_f = merged_shots[idx + 1][0]["frame_idx"] if idx + 1 < len(merged_shots) else total_frames
        shot_anchors.append((anchor, start_f, next_start_f))

    trajectory: List[Tuple[int, int]] = []
    current_shot_idx = 0
    for fi in range(total_frames):
        while current_shot_idx < len(shot_anchors) - 1 and fi >= shot_anchors[current_shot_idx][2]:
            current_shot_idx += 1
        anchor = shot_anchors[current_shot_idx][0] if shot_anchors else (src_w // 2, default_head_y)
        trajectory.append(anchor)

    return trajectory, use_blur


def _pre_scan_trajectory(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
    profile_cascade: Optional["cv2.CascadeClassifier"] = None,
    upperbody_cascade: Optional["cv2.CascadeClassifier"] = None,
) -> Tuple[List[Tuple[int, int]], bool]:
    """Single-focus wrapper executing Pass 1 (Discovery) + Pass 2 (Refinement)."""
    crop_w, _ = _crop_dims(src_w, src_h)
    samples, union_widths = _pre_scan_samples_single(
        cap, src_w, src_h, total_frames, fps, face_cascade, profile_cascade, upperbody_cascade
    )
    return _audit_and_refine_trajectory(
        samples, union_widths, src_w, src_h, total_frames, fps, crop_w, cap=cap
    )


def _pre_scan_samples_pair(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
    profile_cascade: Optional["cv2.CascadeClassifier"] = None,
    upperbody_cascade: Optional["cv2.CascadeClassifier"] = None,
) -> Tuple[List[Dict[str, Any]], List[Tuple[float, float, float]], List[int]]:
    """Pass 1 (Podcast Split): Coarse Discovery pre-scan sampling.

    Gathers face coordinates, speaker spatial halves, candidate cuts, and lip/jaw motion energy.
    """
    sample_every = max(1, int(fps / _PRE_SCAN_FPS))
    mid = src_w // 2

    samples: List[Dict[str, Any]] = []
    prev_small: Optional["np.ndarray"] = None
    prev_mouth_l: Optional["np.ndarray"] = None
    prev_mouth_r: Optional["np.ndarray"] = None
    mouth_activity: List[Tuple[float, float, float]] = []
    all_face_heights: List[int] = []

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            time_s = frame_idx / fps if fps > 0 else 0.0
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (160, 90))
            is_cut = False
            if prev_small is not None:
                diff = float(np.mean(cv2.absdiff(small, prev_small)))
                if diff > 28.0:
                    is_cut = True
            else:
                is_cut = True
            prev_small = small

            faces = _detect_all_faces(gray, src_w, src_h, face_cascade, profile_cascade, upperbody_cascade)
            for f in faces:
                all_face_heights.append(f[3])

            lb = [b for b in faces if (b[0] + b[2] // 2) < (mid + int(src_w * 0.04))]
            rb = [b for b in faces if (b[0] + b[2] // 2) >= (mid - int(src_w * 0.04))]

            lx = ly = lw = lh = None
            rx = ry = rw = rh = None
            if lb:
                b = lb[0]
                lx, ly, lw, lh = b[0] + b[2] // 2, b[1] + b[3] // 2, b[2], b[3]
            if rb:
                b = rb[0]
                rx, ry, rw, rh = b[0] + b[2] // 2, b[1] + b[3] // 2, b[2], b[3]

            # Measure mouth motion energy for active speaker detection
            diff_l = 0.0
            diff_r = 0.0
            if lb and lw and lh:
                my0 = min(src_h - 2, ly + int(lh * 0.10))
                my1 = min(src_h, my0 + int(lh * 0.40))
                mx0 = max(0, lx - int(lw * 0.30))
                mx1 = min(src_w, lx + int(lw * 0.30))
                if my1 > my0 and mx1 > mx0:
                    patch = cv2.resize(gray[my0:my1, mx0:mx1], (32, 24))
                    if prev_mouth_l is not None:
                        diff_l = float(np.mean(cv2.absdiff(patch, prev_mouth_l)))
                    prev_mouth_l = patch

            if rb and rw and rh:
                my0 = min(src_h - 2, ry + int(rh * 0.10))
                my1 = min(src_h, my0 + int(rh * 0.40))
                mx0 = max(0, rx - int(rw * 0.30))
                mx1 = min(src_w, rx + int(rw * 0.30))
                if my1 > my0 and mx1 > mx0:
                    patch = cv2.resize(gray[my0:my1, mx0:mx1], (32, 24))
                    if prev_mouth_r is not None:
                        diff_r = float(np.mean(cv2.absdiff(patch, prev_mouth_r)))
                    prev_mouth_r = patch

            mouth_activity.append((time_s, diff_l, diff_r))

            distinct_two = False
            if lx is not None and rx is not None:
                if abs(rx - lx) > (src_w * 0.22):
                    distinct_two = True

            samples.append({
                "frame_idx": frame_idx,
                "is_cut": is_cut,
                "lx": lx,
                "ly": ly,
                "rx": rx,
                "ry": ry,
                "all_faces": faces,
                "distinct_two": distinct_two,
            })
        frame_idx += 1

    return samples, mouth_activity, all_face_heights


def _audit_and_refine_trajectory_pair(
    samples: List[Dict[str, Any]],
    mouth_activity: List[Tuple[float, float, float]],
    all_face_heights: List[int],
    src_w: int,
    src_h: int,
    total_frames: int,
    fps: float,
    cap: Optional["cv2.VideoCapture"] = None,
) -> Tuple[
    List[Tuple[int, int]],
    List[Tuple[int, int]],
    List[bool],
    List[Tuple[int, int]],
    List[Tuple[float, float, float]],
    float,
    List[float],
]:
    """Pass 2 (Podcast Split): Imperfection Audit & Refinement Pass.

    Audits the coarse detections from Pass 1, catching and correcting:
      1. False-positive micro-shots (<1.2s) caused by sudden lighting or gestures.
      2. Exact sub-second cut boundary alignment (scans localized window to pinpoint exact frame).
      3. Solo vs Dual shot discrepancies (heals 1-frame face dropouts in 2-person shots,
         prunes ghost second faces in 1-person shots).
      4. Horizontal anchor separation (guarantees >= 20% width between Left and Right).
      5. Vertical headroom validation (clamps anchors within 15%..48% safe head height).
      6. Smoothed adaptive bust scaling and cleaned mouth motion energy.
    """
    default_head_y = int(src_h * 0.28)

    # 1. Group raw samples into candidate shots based on scene cuts
    raw_shots: List[List[Dict[str, Any]]] = []
    current_shot: List[Dict[str, Any]] = []
    for s in samples:
        if s["is_cut"] and current_shot:
            raw_shots.append(current_shot)
            current_shot = []
        current_shot.append(s)
    if current_shot:
        raw_shots.append(current_shot)

    # 2. Imperfection 1: Filter false-positive micro-cuts (<1.2s)
    min_shot_samples = max(2, int(1.2 * _PRE_SCAN_FPS))
    merged_shots: List[List[Dict[str, Any]]] = []
    for shot in raw_shots:
        if merged_shots and len(shot) < min_shot_samples:
            prev = merged_shots[-1]
            prev_l = [s["lx"] for s in prev if s["lx"] is not None]
            cur_l = [s["lx"] for s in shot if s["lx"] is not None]
            if prev_l and cur_l and abs(np.median(cur_l) - np.median(prev_l)) < (src_w * 0.08):
                merged_shots[-1].extend(shot)
                continue
        merged_shots.append(shot)

    # 2b. Exact Scene Cut Refinement: Pinpoint cut boundaries to exact frame
    refined_cuts: List[int] = []
    if cap is not None and len(merged_shots) > 1:
        for idx in range(len(merged_shots) - 1):
            f_prev = merged_shots[idx][-1]["frame_idx"]
            f_curr = merged_shots[idx + 1][0]["frame_idx"]
            exact_f = _refine_cut_frame(cap, f_prev, f_curr)
            merged_shots[idx + 1][0]["frame_idx"] = exact_f
            refined_cuts.append(exact_f)

    cut_timestamps: List[float] = [f / fps for f in refined_cuts if fps > 0]

    # 3. Imperfection 2 & 3: Audit Shot Consistency, Dropout Healing, and Anchor Separation
    shot_data: List[Dict[str, Any]] = []
    last_l = (src_w // 4, default_head_y)
    last_r = (src_w * 3 // 4, default_head_y)
    last_solo = (src_w // 2, default_head_y)

    for idx, shot in enumerate(merged_shots):
        start_f = shot[0]["frame_idx"]
        next_start_f = merged_shots[idx + 1][0]["frame_idx"] if idx + 1 < len(merged_shots) else total_frames

        valid_samples = [s for s in shot if len(s["all_faces"]) > 0]
        two_person_count = sum(1 for s in shot if s["distinct_two"])
        total_valid = len(valid_samples)

        # Shot classification audit:
        # If >= 35% of valid frames show 2 distinct people, enforce DUAL shot for the entire shot
        # (heals temporary dropouts where one speaker looked down or sipped water)
        if total_valid > 0:
            is_solo_shot = (two_person_count / max(1, total_valid)) < 0.35
        else:
            is_solo_shot = shot_data[-1]["is_solo"] if shot_data else False

        # Calculate stable median anchors
        left_xs = [s["lx"] for s in shot if s["lx"] is not None]
        left_ys = [s["ly"] for s in shot if s["ly"] is not None]
        right_xs = [s["rx"] for s in shot if s["rx"] is not None]
        right_ys = [s["ry"] for s in shot if s["ry"] is not None]

        raw_al = (int(np.median(left_xs)), int(np.median(left_ys))) if (left_xs and left_ys) else last_l
        raw_ar = (int(np.median(right_xs)), int(np.median(right_ys))) if (right_xs and right_ys) else last_r

        # Enforce minimum horizontal separation in dual shots
        al_x, al_y = raw_al
        ar_x, ar_y = raw_ar
        min_sep = int(src_w * 0.20)
        if not is_solo_shot and (ar_x - al_x < min_sep):
            al_x = min(al_x, src_w // 3)
            ar_x = max(ar_x, src_w * 2 // 3)

        # Enforce safe headroom bounds: clamp y to 15%..48% of source height
        min_head_y = int(src_h * 0.15)
        max_head_y = int(src_h * 0.48)
        al_y = max(min_head_y, min(max_head_y, al_y))
        ar_y = max(min_head_y, min(max_head_y, ar_y))

        anchor_l = (al_x, al_y)
        anchor_r = (ar_x, ar_y)
        last_l, last_r = anchor_l, anchor_r

        # Solo anchor
        all_cxs = []
        all_cys = []
        for s in shot:
            for f in s["all_faces"]:
                all_cxs.append(f[0] + f[2] // 2)
                all_cys.append(f[1] + f[3] // 2)
        if all_cxs and all_cys:
            solo_x = int(np.median(all_cxs))
            solo_y = max(min_head_y, min(max_head_y, int(np.median(all_cys))))
            anchor_solo = (solo_x, solo_y)
            last_solo = anchor_solo
        else:
            anchor_solo = last_solo

        shot_data.append({
            "start_f": start_f,
            "end_f": next_start_f,
            "is_solo": is_solo_shot,
            "anchor_l": anchor_l,
            "anchor_r": anchor_r,
            "anchor_solo": anchor_solo,
        })

    # 4. Imperfection 4: Adaptive Bust Scale Calculation
    if all_face_heights:
        med_h = float(np.median(all_face_heights))
        ratio = med_h / max(1, src_h)
        if ratio < 0.11:
            adaptive_bust_scale = 0.72
        elif ratio > 0.22:
            adaptive_bust_scale = 0.88
        else:
            adaptive_bust_scale = 0.80
    else:
        adaptive_bust_scale = 0.82

    # 5. Build perfected per-frame trajectories
    traj_left: List[Tuple[int, int]] = []
    traj_right: List[Tuple[int, int]] = []
    solo_mask: List[bool] = []
    solo_traj: List[Tuple[int, int]] = []

    current_shot_idx = 0
    for fi in range(total_frames):
        while current_shot_idx < len(shot_data) - 1 and fi >= shot_data[current_shot_idx]["end_f"]:
            current_shot_idx += 1
        cur = shot_data[current_shot_idx] if shot_data else {
            "is_solo": False,
            "anchor_l": (src_w // 4, default_head_y),
            "anchor_r": (src_w * 3 // 4, default_head_y),
            "anchor_solo": (src_w // 2, default_head_y),
        }
        traj_left.append(cur["anchor_l"])
        traj_right.append(cur["anchor_r"])
        solo_mask.append(cur["is_solo"])
        solo_traj.append(cur["anchor_solo"])

    return traj_left, traj_right, solo_mask, solo_traj, mouth_activity, adaptive_bust_scale, cut_timestamps


def _pre_scan_trajectory_pair(
    cap: "cv2.VideoCapture",
    src_w: int, src_h: int,
    total_frames: int, fps: float,
    face_cascade: "cv2.CascadeClassifier",
    profile_cascade: Optional["cv2.CascadeClassifier"] = None,
    upperbody_cascade: Optional["cv2.CascadeClassifier"] = None,
) -> Tuple[
    List[Tuple[int, int]],
    List[Tuple[int, int]],
    List[bool],
    List[Tuple[int, int]],
    List[Tuple[float, float, float]],
    float,
    List[float],
]:
    """Podcast split wrapper executing Pass 1 (Discovery) + Pass 2 (Refinement)."""
    samples, mouth_activity, all_face_heights = _pre_scan_samples_pair(
        cap, src_w, src_h, total_frames, fps, face_cascade, profile_cascade, upperbody_cascade
    )
    return _audit_and_refine_trajectory_pair(
        samples, mouth_activity, all_face_heights, src_w, src_h, total_frames, fps, cap=cap
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


def _calculate_zoom_factor(
    clip_time: float,
    segments: Optional[List[Dict]] = None,
    enabled: bool = True,
    zoom_scale: float = 1.15,
) -> float:
    """Calculate the zoom factor (1.0 or 1.15) for dynamic visual retention.

    Alternates between a standard medium shot (1.0x) and a close-up punch-in
    (1.15x) on sentence boundaries (or every ~4s) to reset viewer attention
    and simulate a multi-camera studio setup.
    """
    if not enabled or zoom_scale <= 1.0:
        return 1.0

    # If segments are available, align camera cuts with natural speech boundaries
    if segments:
        for i, seg in enumerate(segments):
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
            if start <= clip_time < end:
                seg_dur = end - start
                if seg_dur > 5.0:
                    sub_idx = int((clip_time - start) // 3.5)
                    return zoom_scale if ((i + sub_idx) % 2 == 1) else 1.0
                return zoom_scale if (i % 2 == 1) else 1.0

    # Fallback to rhythmic 4.0s cadence
    cadence = 4.0
    period_idx = int(clip_time // cadence)
    return zoom_scale if (period_idx % 2 == 1) else 1.0


def _render_full_bleed_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx: int, cy: int,
    zoom: float = 1.0,
    clamp_half: Optional[str] = None,
) -> "np.ndarray":
    """Full-bleed 9:16 portrait canvas (1080x1920) edge-to-edge.

    Dynamically tracks the speaker's face, keeping eyes and head framed naturally
    in the upper third (~28% from top) and torso below. No black bars, no floating box.
    """
    aspect = 9.0 / 16.0
    if src_h * aspect <= src_w:
        base_ch = src_h
        base_cw = int(base_ch * aspect)
    else:
        base_cw = src_w
        base_ch = int(base_cw / aspect)

    z = max(1.0, float(zoom))
    cw = max(2, int(base_cw / z))
    ch = max(2, int(base_ch / z))
    cw -= cw % 2
    ch -= ch % 2

    # Horizontal center on tracked face with optional half-width clamping
    mid = src_w // 2
    if clamp_half == "left" and cw <= mid:
        x0 = max(0, min(mid - cw, cx - cw // 2))
    elif clamp_half == "right" and cw <= mid:
        x0 = max(mid, min(src_w - cw, cx - cw // 2))
    else:
        x0 = max(0, min(src_w - cw, cx - cw // 2))

    # Vertical positioning: place eyes/head in upper third
    head_frac = 0.28
    y0 = max(0, min(src_h - ch, cy - int(ch * head_frac)))

    region = frame[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(region, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_LINEAR)


def _render_blurred_backdrop_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx: Optional[int] = None,
    cy: Optional[int] = None,
    zoom: float = 1.0,
) -> "np.ndarray":
    """Ambient blurred backdrop with sharp foreground video centered.

    Never leaves solid black voids. Background is scaled to fill 1080x1920,
    heavily blurred and darkened by 45%. Foreground video is centered
    maintaining aspect ratio with crisp framing.
    """
    # 1. Background layer: cover 1080x1920, blur and darken
    bg_scale = max(CANVAS_W / src_w, CANVAS_H / src_h)
    bg_w = int(src_w * bg_scale)
    bg_h = int(src_h * bg_scale)
    bg_full = cv2.resize(frame, (bg_w, bg_h), interpolation=cv2.INTER_LINEAR)

    bg_x = max(0, (bg_w - CANVAS_W) // 2)
    bg_y = max(0, (bg_h - CANVAS_H) // 2)
    bg = bg_full[bg_y:bg_y + CANVAS_H, bg_x:bg_x + CANVAS_W]
    if bg.shape[0] != CANVAS_H or bg.shape[1] != CANVAS_W:
        bg = cv2.resize(bg, (CANVAS_W, CANVAS_H))

    # Fast two-pass blur
    small = cv2.resize(bg, (135, 240), interpolation=cv2.INTER_LINEAR)
    blurred_small = cv2.GaussianBlur(small, (25, 25), 0)
    bg = cv2.resize(blurred_small, (CANVAS_W, CANVAS_H), interpolation=cv2.INTER_LINEAR)
    # Darken so foreground stands out
    bg = (bg.astype(np.float32) * 0.45).astype(np.uint8)

    # 2. Foreground layer: fit within width CANVAS_W and center vertically
    z = max(1.0, float(zoom))
    fg_scale = (CANVAS_W / src_w) * z
    fg_w = int(src_w * fg_scale)
    fg_h = int(src_h * fg_scale)
    fg_resized = cv2.resize(frame, (fg_w, fg_h), interpolation=cv2.INTER_LINEAR)

    # Center crop foreground if it exceeds canvas bounds
    if fg_w > CANVAS_W or fg_h > CANVAS_H:
        start_x = max(0, (fg_w - CANVAS_W) // 2)
        start_y = max(0, (fg_h - CANVAS_H) // 2)
        crop_fg_w = min(CANVAS_W, fg_w)
        crop_fg_h = min(CANVAS_H, fg_h)
        fg_cropped = fg_resized[start_y:start_y + crop_fg_h, start_x:start_x + crop_fg_w]
        fg_y0 = max(0, (CANVAS_H - crop_fg_h) // 2)
        fg_x0 = max(0, (CANVAS_W - crop_fg_w) // 2)
        bg[fg_y0:fg_y0 + crop_fg_h, fg_x0:fg_x0 + crop_fg_w] = fg_cropped
    else:
        fg_y0 = max(0, (CANVAS_H - fg_h) // 2)
        fg_x0 = max(0, (CANVAS_W - fg_w) // 2)
        bg[fg_y0:fg_y0 + fg_h, fg_x0:fg_x0 + fg_w] = fg_resized

    return bg


def _render_stage_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx: int, cy: int,
    zoom: float = 1.0,
) -> "np.ndarray":
    """Stage & Solo Speaker: Video fills the primary stage (1080x1152) with an
    ambient blurred background filling top and bottom safe zones (no pitch-black bars).
    """
    canvas = _render_blurred_backdrop_canvas(frame, src_w, src_h, cx, cy, zoom=zoom)
    stage_w, stage_h = CANVAS_W, STAGE_H          # 1080 x 1152 primary stage (60%)
    stage_y0 = TOP_SAFE_H                         # 441px (23%)
    aspect = stage_w / stage_h                  # 0.9375

    if src_h * aspect <= src_w:
        ch = src_h
        cw = int(ch * aspect)
    else:
        cw = src_w
        ch = int(cw / aspect)

    z = max(1.0, float(zoom))
    cw = max(2, int(cw / z))
    ch = max(2, int(ch / z))
    cw -= cw % 2
    ch -= ch % 2

    x0 = max(0, min(src_w - cw, cx - cw // 2))
    head_frac = 0.20
    y0 = max(0, min(src_h - ch, cy - int(ch * head_frac)))
    region = frame[y0:y0 + ch, x0:x0 + cw]
    stage = cv2.resize(region, (stage_w, stage_h))
    canvas[stage_y0:stage_y0 + stage_h, :, :] = stage
    return canvas


def _compute_podcast_solo_windows(
    duration: float,
    segments: Optional[List[Dict]] = None,
    enabled: bool = True,
    period: float = 8.0,
    solo_dur: float = 2.6,
    initial_delay: float = 3.5,
    mouth_activity: Optional[List[Tuple[float, float, float]]] = None,
    solo_mask: Optional[List[bool]] = None,
    fps: float = 30.0,
    cut_timestamps: Optional[List[float]] = None,
) -> List[Tuple[float, float, int]]:
    """Compute timestamps for dynamic full-vertical solo cuts during a podcast split.

    Uses mouth/jaw motion energy from Pass 1 to ensure that when cutting to a full-screen
    vertical solo shot, the person displayed is ALWAYS the host who is actively talking.
    If the shot is already a single-person camera angle (solo_mask is True), artificial cuts
    are skipped because the shot is already rendered full-bleed solo.
    """
    if not enabled or duration < (initial_delay + solo_dur + 1.0):
        return []

    # Gather candidate sentence boundaries from transcript
    sentence_cuts: List[float] = []
    if segments:
        for seg in segments:
            seg_start = float(seg.get("start", 0.0))
            text = seg.get("text", "")
            words = seg.get("words") or []
            if words:
                for idx, w in enumerate(words[:-1]):
                    w_text = str(w.get("word", ""))
                    if any(p in w_text for p in ".!?"):
                        next_start = float(words[idx + 1].get("start", 0.0))
                        sentence_cuts.append(next_start)
            else:
                for m in re.finditer(r"[.!?]", text):
                    frac = m.end() / max(1, len(text))
                    seg_dur = max(0.1, float(seg.get("end", seg_start)) - seg_start)
                    sentence_cuts.append(seg_start + frac * seg_dur)

    windows: List[Tuple[float, float, int]] = []
    cur_t = initial_delay

    while cur_t + solo_dur <= duration - 1.0:
        # Snap start time to nearest sentence cut within 1.5s window if available
        chosen_start = cur_t
        for sc in sentence_cuts:
            if abs(sc - cur_t) <= 1.5 and sc + solo_dur <= duration - 0.5:
                chosen_start = sc
                break

        # Snap start time to nearest true scene cut within 1.2s if available
        if cut_timestamps:
            for ct in cut_timestamps:
                if abs(ct - chosen_start) <= 1.2 and ct + solo_dur <= duration - 0.5:
                    chosen_start = ct
                    break

        chosen_end = min(duration - 0.5, chosen_start + solo_dur)

        # Do not allow dynamic solo window to span across a real scene cut
        if cut_timestamps:
            for ct in cut_timestamps:
                if chosen_start < ct < chosen_end:
                    chosen_end = ct
                    break

        if chosen_end - chosen_start < 1.2:
            cur_t = chosen_end + max(2.5, (period - solo_dur))
            continue

        # If this window is already in a solo-camera shot, skip artificial solo cut
        if solo_mask and fps > 0:
            sf = int(chosen_start * fps)
            ef = min(len(solo_mask), int(chosen_end * fps))
            if sf < len(solo_mask) and any(solo_mask[sf:ef]):
                cur_t = chosen_end + max(2.5, (period - solo_dur))
                continue

        # Active speaker detection: evaluate mouth motion energy during [chosen_start, chosen_end]
        chosen_spk = 0
        if mouth_activity:
            window_samples = [s for s in mouth_activity if chosen_start <= s[0] <= chosen_end]
            if window_samples:
                avg_l = float(np.mean([s[1] for s in window_samples]))
                avg_r = float(np.mean([s[2] for s in window_samples]))

                if avg_l > avg_r * 1.12:
                    chosen_spk = 0  # Left speaker active
                elif avg_r > avg_l * 1.12:
                    chosen_spk = 1  # Right speaker active
                else:
                    # If mouth motion is virtually zero on both, both are quiet/listening: skip cut
                    if avg_l < 1.0 and avg_r < 1.0:
                        cur_t = chosen_end + max(2.5, (period - solo_dur))
                        continue
                    chosen_spk = 0 if avg_l >= avg_r else 1

        windows.append((chosen_start, chosen_end, chosen_spk))
        cur_t = chosen_end + max(2.5, (period - solo_dur))

    return windows


def _render_podcast_canvas(
    frame: "np.ndarray",
    src_w: int, src_h: int,
    cx_left: int, cy_left: int,
    cx_right: int, cy_right: int,
    crop_scale: float = 0.82,
    head_frac: float = 0.38,
) -> "np.ndarray":
    """Template 2 (Podcast & Dialogue): two stacked 9:8 panels (1080x960
    each) on the 1080x1920 canvas.

    Each panel crops a Medium-Bust (chest-up) 9:8 region around its speaker's
    tracked face with generous headroom protection, ensuring heads are never cut off.
    """
    panel_w, panel_h = CANVAS_W, CANVAS_H // 2  # 1080 x 960 (9:8)
    aspect = 9.0 / 8.0

    def _panel(cx: int, cy: int) -> "np.ndarray":
        # Target medium-bust dimensions
        target_ch = int(src_h * max(0.5, min(1.0, crop_scale)))
        target_cw = int(target_ch * aspect)

        # Bounds safety check against source dimensions
        if target_cw > src_w:
            target_cw = src_w
            target_ch = int(target_cw / aspect)
        if target_ch > src_h:
            target_ch = src_h
            target_cw = int(target_ch * aspect)

        target_ch -= target_ch % 2
        target_cw -= target_cw % 2
        target_cw = max(2, target_cw)
        target_ch = max(2, target_ch)

        # Horizontal center on tracked speaker
        x0 = max(0, min(src_w - target_cw, cx - target_cw // 2))

        # Vertical head placement with headroom protection:
        # Places head at ~38% of panel height, clamped at top y=0 so forehead/hair is never cropped
        y0 = max(0, min(src_h - target_ch, cy - int(target_ch * head_frac)))

        region = frame[y0:y0 + target_ch, x0:x0 + target_cw]
        return cv2.resize(region, (panel_w, panel_h), interpolation=cv2.INTER_LINEAR)

    top = _panel(cx_left, cy_left)
    bottom = _panel(cx_right, cy_right)
    canvas = cv2.vconcat([top, bottom])
    return canvas


# ── Visual Speaker Pop Filters ──────────────────────────────────────

VIDEO_FILTER_SPECS: Dict[str, Dict[str, Any]] = {
    "vivid_pop": {
        "label": "Vivid Pop (Speaker Focus)",
        "description": "Vibrant skin tones, rich contrast, facial micro-clarity, and spotlight vignette",
    },
    "warm_studio": {
        "label": "Warm Studio",
        "description": "Warm podcast lighting, golden skin tones, and gentle contrast",
    },
    "clean_crisp": {
        "label": "Clean Crisp",
        "description": "Ultra-sharp detail, natural colors, and neutral tone curve",
    },
    "cinematic": {
        "label": "Cinematic Punch",
        "description": "Moody deep blacks, high dynamic range, and dramatic vignette",
    },
    "none": {
        "label": "None (Original)",
        "description": "Raw unadjusted video footage",
    },
}

_FILTER_LUTS: Dict[str, "np.ndarray"] = {}
_SAT_LUTS: Dict[float, "np.ndarray"] = {}
_VIGNETTE_MASKS: Dict[Tuple[int, int, int], "np.ndarray"] = {}

def _get_filter_lut(contrast: float, brightness: float) -> "np.ndarray":
    key = f"{contrast:.2f}_{brightness:.2f}"
    if key not in _FILTER_LUTS:
        import numpy as np
        lut = np.clip((np.arange(256, dtype=np.float32) - 128.0) * contrast + 128.0 + brightness, 0, 255).astype(np.uint8)
        _FILTER_LUTS[key] = lut
    return _FILTER_LUTS[key]

def _get_sat_lut(scale: float) -> "np.ndarray":
    key = round(scale, 2)
    if key not in _SAT_LUTS:
        import numpy as np
        lut = np.clip(np.arange(256, dtype=np.float32) * scale, 0, 255).astype(np.uint8)
        _SAT_LUTS[key] = lut
    return _SAT_LUTS[key]

def _get_vignette_mask(h: int, w: int, intensity: float = 0.16) -> "np.ndarray":
    key = (h, w, int(intensity * 100))
    if key not in _VIGNETTE_MASKS:
        import numpy as np
        kernel_x = cv2.getGaussianKernel(w, w * 0.75)
        kernel_y = cv2.getGaussianKernel(h, h * 0.75)
        kernel = kernel_y * kernel_x.T
        mask = kernel / (kernel.max() if kernel.max() > 0 else 1.0)
        vignette_u8 = np.clip(((1.0 - intensity) + intensity * mask) * 255.0, 0, 255).astype(np.uint8)
        _VIGNETTE_MASKS[key] = cv2.merge([vignette_u8, vignette_u8, vignette_u8])
    return _VIGNETTE_MASKS[key]

def apply_video_filter(frame: "np.ndarray", filter_name: Optional[str] = "vivid_pop") -> "np.ndarray":
    """Enhance video speakers with contrast, skin tone vibrance, facial sharpening, and spotlight vignette.
    Optimized for real-time OpenCV C++ execution with zero memory reallocation.
    """
    if not filter_name or filter_name == "none":
        return frame

    name = filter_name.lower().strip()

    if name == "vivid_pop":
        # S-curve contrast & slight brightness
        lut = _get_filter_lut(contrast=1.10, brightness=2.0)
        graded = cv2.LUT(frame, lut)
        # Skin tone & color vibrance (+18%) via single-channel saturation LUT
        hsv = cv2.cvtColor(graded, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.LUT(hsv[:, :, 1], _get_sat_lut(1.18))
        graded = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        # Facial micro-contrast / unsharp mask (+35%)
        blurred = cv2.GaussianBlur(graded, (0, 0), 1.5)
        sharpened = cv2.addWeighted(graded, 1.35, blurred, -0.35, 0)
        # Spotlight vignette (-16%) via fast C++ multiply
        vignette_3ch = _get_vignette_mask(frame.shape[0], frame.shape[1], intensity=0.16)
        return cv2.multiply(sharpened, vignette_3ch, scale=1.0 / 255.0)

    elif name == "warm_studio":
        lut = _get_filter_lut(contrast=1.08, brightness=3.0)
        graded = cv2.LUT(frame, lut)
        # Warm tone shift: slight amber/red boost
        graded[:, :, 2] = cv2.LUT(graded[:, :, 2], _get_sat_lut(1.04))
        hsv = cv2.cvtColor(graded, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.LUT(hsv[:, :, 1], _get_sat_lut(1.14))
        graded = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        blurred = cv2.GaussianBlur(graded, (0, 0), 1.5)
        sharpened = cv2.addWeighted(graded, 1.25, blurred, -0.25, 0)
        vignette_3ch = _get_vignette_mask(frame.shape[0], frame.shape[1], intensity=0.14)
        return cv2.multiply(sharpened, vignette_3ch, scale=1.0 / 255.0)

    elif name == "clean_crisp":
        lut = _get_filter_lut(contrast=1.06, brightness=1.0)
        graded = cv2.LUT(frame, lut)
        blurred = cv2.GaussianBlur(graded, (0, 0), 1.5)
        return cv2.addWeighted(graded, 1.45, blurred, -0.45, 0)

    elif name == "cinematic":
        lut = _get_filter_lut(contrast=1.16, brightness=-2.0)
        graded = cv2.LUT(frame, lut)
        hsv = cv2.cvtColor(graded, cv2.COLOR_BGR2HSV)
        hsv[:, :, 1] = cv2.LUT(hsv[:, :, 1], _get_sat_lut(1.10))
        graded = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        blurred = cv2.GaussianBlur(graded, (0, 0), 1.5)
        sharpened = cv2.addWeighted(graded, 1.28, blurred, -0.28, 0)
        vignette_3ch = _get_vignette_mask(frame.shape[0], frame.shape[1], intensity=0.22)
        return cv2.multiply(sharpened, vignette_3ch, scale=1.0 / 255.0)

    return frame


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
    """Dynamic word-by-word caption with high-contrast outline and drop shadow."""
    words = [w for w in words if w]
    if not words:
        return canvas
    total = len(words)
    current_idx = max(0, min(current_idx, total - 1))

    # Fixed burst: floor(current_idx / MAX_CAPTION_WORDS) * MAX_CAPTION_WORDS.
    batch_start = (current_idx // MAX_CAPTION_WORDS) * MAX_CAPTION_WORDS
    window = words[batch_start:batch_start + MAX_CAPTION_WORDS]

    font = cv2.FONT_HERSHEY_TRIPLEX
    base_scale = CAPTION_FONT_SCALE
    thick = CAPTION_FONT_THICK
    white = (255, 255, 255)  # Inactive words are always pure white

    custom_color = (style or {}).get("color")
    if custom_color and custom_color.strip().upper() not in ("#FFFFFF", "#FFF", "WHITE"):
        accent = tuple(reversed(_parse_hex(custom_color)))
    else:
        accent = (0, 234, 255)  # Electric Yellow in BGR

    disp_words = [w.upper() for w in window]
    safe_cap_w = int(CANVAS_W * 0.80)
    cur_base_scale = base_scale
    while cur_base_scale > 0.8:
        space_w = cv2.getTextSize(" ", font, cur_base_scale, thick)[0][0] + 8
        total_w = sum(
            cv2.getTextSize(w, font, cur_base_scale * 1.18 if (batch_start + i == current_idx) else cur_base_scale, thick)[0][0]
            for i, w in enumerate(disp_words)
        ) + max(0, len(disp_words) - 1) * space_w
        if total_w <= safe_cap_w:
            break
        cur_base_scale -= 0.15

    x0 = max(108, (CANVAS_W - total_w) // 2)
    y0 = band_y0 + (band_y1 - band_y0) // 2 + 20

    cur_x = x0
    word_idx = batch_start
    for w in disp_words:
        is_current = (word_idx == current_idx)
        color = accent if is_current else white
        cur_scale = cur_base_scale * 1.18 if is_current else cur_base_scale
        cur_thick = thick + (1 if is_current else 0)
        ww = cv2.getTextSize(w, font, cur_scale, cur_thick)[0][0]

        # 1. Shadow
        cv2.putText(canvas, w, (cur_x + 4, y0 + 5), font, cur_scale, (0, 0, 0), cur_thick + 8, cv2.LINE_AA)
        # 2. Outer stroke
        cv2.putText(canvas, w, (cur_x, y0), font, cur_scale, (0, 0, 0), cur_thick + 6, cv2.LINE_AA)
        # 3. Main text fill
        cv2.putText(canvas, w, (cur_x, y0), font, cur_scale, color, cur_thick, cv2.LINE_AA)

        cur_x += ww + space_w
        word_idx += 1
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
        x0 = max(108, (CANVAS_W - block_w) // 2)
        y0 = band_y0 + (band_y1 - band_y0 - block_h) // 2
        return _composite_rgba(canvas, rgba, x0, y0)
    return _draw_word_caption_cv(canvas, words, current_idx, band_y0, band_y1, style)


def _draw_hook_card(
    canvas: "np.ndarray",
    title: str,
    time: float = 0.0,
    style: Optional[Dict] = None,
) -> "np.ndarray":
    """Agency-grade Opening Hook Card (first 2.5 seconds of clip).

    Renders a bold, high-contrast headline pill badge in the upper third
    safe zone (above the speaker's face and kinetic captions). Smoothly
    fades out between 2.0s and 2.5s.
    """
    if not title or time > 2.5:
        return canvas

    if time <= 2.0:
        fade = 1.0
    else:
        fade = max(0.0, min(1.0, (2.5 - time) / 0.5))

    if fade <= 0.01:
        return canvas

    clean_title = title.strip().upper()
    # If title is excessively long, truncate gracefully with ellipsis
    if len(clean_title) > 45:
        words = clean_title.split()
        shortened = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + 1 > 42:
                break
            shortened.append(w)
            cur_len += len(w) + 1
        clean_title = " ".join(shortened) + "..."

    if _HAS_PIL:
        try:
            font_size = 44
            font_token = (style or {}).get("font") or "impact"
            font = _resolve_font(font_token, font_size)

            probe_img = Image.new("RGBA", (1, 1))
            probe_draw = ImageDraw.Draw(probe_img)
            tw = probe_draw.textlength(clean_title, font=font)

            max_w = CANVAS_W - 140
            if tw > max_w:
                font_size = max(26, int(font_size * (max_w / tw)))
                font = _resolve_font(font_token, font_size)
                tw = probe_draw.textlength(clean_title, font=font)

            pad_x = 34
            pad_y = 16
            badge_w = int(tw) + 2 * pad_x
            badge_h = font_size + 2 * pad_y + 6

            badge = Image.new("RGBA", (badge_w + 30, badge_h + 30), (0, 0, 0, 0))
            d = ImageDraw.Draw(badge)

            # 1. Floating drop shadow
            d.rounded_rectangle(
                [10, 14, 10 + badge_w, 14 + badge_h],
                radius=18,
                fill=(0, 0, 0, int(150 * fade)),
            )

            # 2. Obsidian glass pill background with Electric Yellow accent border
            d.rounded_rectangle(
                [10, 10, 10 + badge_w, 10 + badge_h],
                radius=18,
                fill=(14, 16, 20, int(230 * fade)),
                outline=(255, 234, 0, int(240 * fade)),
                width=3,
            )

            # 3. Clean headline typography with drop shadow
            tx = 10 + pad_x
            ty = 10 + pad_y
            d.text((tx + 2, ty + 2), clean_title, font=font, fill=(0, 0, 0, int(220 * fade)))
            d.text((tx, ty), clean_title, font=font, fill=(255, 255, 255, int(255 * fade)))

            arr = np.array(badge)
            bx = (CANVAS_W - arr.shape[1]) // 2
            by = 220  # Upper third safe zone
            return _composite_rgba(canvas, arr, bx, by)
        except Exception:
            pass

    # OpenCV fallback
    scale = 1.0
    thick = 2
    font = cv2.FONT_HERSHEY_DUPLEX
    (tw, th), _ = cv2.getTextSize(clean_title, font, scale, thick)
    while tw > CANVAS_W - 140 and scale > 0.5:
        scale -= 0.05
        (tw, th), _ = cv2.getTextSize(clean_title, font, scale, thick)

    pad_x, pad_y = 25, 15
    bx0 = (CANVAS_W - tw) // 2 - pad_x
    by0 = 220
    bx1 = bx0 + tw + 2 * pad_x
    by1 = by0 + th + 2 * pad_y

    overlay = canvas.copy()
    cv2.rectangle(overlay, (bx0, by0), (bx1, by1), (14, 16, 20), -1)
    cv2.rectangle(overlay, (bx0, by0), (bx1, by1), (0, 234, 255), 2)  # BGR electric yellow
    cv2.putText(overlay, clean_title, (bx0 + pad_x, by0 + pad_y + th), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
    return cv2.addWeighted(overlay, fade, canvas, 1.0 - fade, 0)


def _draw_hook_title(canvas: "np.ndarray", title: str) -> "np.ndarray":
    """Backward-compatible wrapper for hook headline at time=0.0."""
    return _draw_hook_card(canvas, title, time=0.0)



def _draw_divider(canvas: "np.ndarray", layout_type: str, is_solo: bool = False) -> "np.ndarray":
    """2px accent divider line for the podcast split at y ~960px."""
    if layout_type != "split_vertical" or is_solo:
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
    is_solo: bool = False,
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
    effective_layout = "single_focus" if is_solo else layout_type
    typo = spec.get("typography") or {}

    # Color overlay
    overlay_color = spec.get("layout", {}).get("color_overlay")
    if overlay_color is not None and len(overlay_color) == 4:
        r, g, b = overlay_color[0], overlay_color[1], overlay_color[2]
        alpha = overlay_color[3]
        tint = np.full_like(out, [b, g, r], dtype=np.uint8)
        out = cv2.addWeighted(out, 1.0 - alpha, tint, alpha, 0)

    # Divider line (podcast split) - only shown when in split mode
    out = _draw_divider(out, layout_type, is_solo=is_solo)

    # Agency Visual Hook Card (first 2.5 seconds of the clip across all layouts)
    hook_enabled = True
    if style and "hook_card" in style:
        hook_enabled = bool(style["hook_card"])
    elif "hook_card" in spec:
        hook_enabled = bool(spec["hook_card"])

    if hook_enabled and time <= 2.5:
        title = typo.get("title", "") or spec.get("title", "")
        if not title and segments:
            first_text = (segments[0].get("text") or "").strip()
            if first_text:
                first_sent = re.split(r"[.!?\n]", first_text)[0].strip()
                words = first_sent.split()
                title = " ".join(words[:7]) if len(words) > 7 else first_sent
        if title:
            out = _draw_hook_card(out, title, time=time, style=style)

    # Word-by-word captions (real transcript segments when available)
    text = typo.get("text", "")
    pos = style.get("position") if style else None
    band_y0, band_y1 = _band_for_position(pos, layout_type, is_solo=is_solo)
    if segments:
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
    profile_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_profileface.xml"
    )
    upperbody_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_upperbody.xml"
    )

    # ── Pass 1 & Pass 2: Discovery & Imperfection Audit ──
    auto_framing = spec.get("auto_framing", True)
    layout_type = spec.get("layout", {}).get("type", "single_focus")
    layout_spec = spec.get("layout", {})

    trajectory: Optional[List[Tuple[int, int]]] = None
    traj_left: Optional[List[Tuple[int, int]]] = None
    traj_right: Optional[List[Tuple[int, int]]] = None
    solo_mask: Optional[List[bool]] = None
    solo_traj: Optional[List[Tuple[int, int]]] = None
    mouth_activity: Optional[List[Tuple[float, float, float]]] = None
    cut_timestamps: Optional[List[float]] = None
    adaptive_bust_scale = 0.82
    use_blur = False
    if auto_framing:
        if layout_type == "split_vertical":
            print("  [Pass 1/3: Discovery] Pre-scanning scene cuts, speaker clusters & active speech...", flush=True)
            samples, raw_mouth, face_heights = _pre_scan_samples_pair(
                cap, src_w, src_h, total_frames, fps,
                face_cascade, profile_cascade, upperbody_cascade
            )
            print("  [Pass 2/3: Refinement] Auditing shot imperfections, healing dropouts & locking anchors...", flush=True)
            (
                traj_left,
                traj_right,
                solo_mask,
                solo_traj,
                mouth_activity,
                adaptive_bust_scale,
                cut_timestamps,
            ) = _audit_and_refine_trajectory_pair(
                samples, raw_mouth, face_heights, src_w, src_h, total_frames, fps, cap=cap
            )
        else:
            print("  [Pass 1/3: Discovery] Pre-scanning scene cuts and face tracking...", flush=True)
            samples, union_widths = _pre_scan_samples_single(
                cap, src_w, src_h, total_frames, fps,
                face_cascade, profile_cascade, upperbody_cascade
            )
            print("  [Pass 2/3: Refinement] Auditing shots, clamping headroom & locking anchors...", flush=True)
            trajectory, use_blur = _audit_and_refine_trajectory(
                samples, union_widths, src_w, src_h, total_frames, fps, crop_w, cap=cap
            )
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

    # ── Pass 3: Final Render ──
    print("  [Pass 3/3: Render] Compositing 1080x1920 short with safe-width kinetic captions...", flush=True)
    silent_path = out_path + ".silent.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out_w, out_h = CANVAS_W, CANVAS_H

    writer = cv2.VideoWriter(silent_path, fourcc, fps, (out_w, out_h))

    # Pre-calculate dynamic solo cuts for podcast split screen
    clip_duration = total_frames / fps if fps > 0 else 0.0
    solo_switch_enabled = spec.get("solo_switch", True)
    if style and "podcast_solo_switch" in style:
        solo_switch_enabled = bool(style["podcast_solo_switch"])

    bust_scale = float(spec.get("bust_scale", adaptive_bust_scale))
    if style and "podcast_bust_scale" in style:
        bust_scale = float(style["podcast_bust_scale"])

    video_filter = spec.get("video_filter", "vivid_pop")
    if style and "video_filter" in style:
        video_filter = style["video_filter"]

    solo_windows: List[Tuple[float, float, int]] = []
    if layout_type == "split_vertical" and solo_switch_enabled:
        solo_windows = _compute_podcast_solo_windows(
            clip_duration,
            segments=segments,
            enabled=True,
            mouth_activity=mouth_activity,
            solo_mask=solo_mask,
            fps=fps,
            cut_timestamps=cut_timestamps,
        )

    frame_idx = 0
    default_cx, default_cy = src_w // 2, src_h // 2
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        pct = frame_idx / total_frames if total_frames > 0 else 0
        clip_time = frame_idx / fps if fps > 0 else 0.0

        zoom_enabled = spec.get("zoom_punch", True)
        if style and "zoom_punch" in style:
            zoom_enabled = bool(style["zoom_punch"])
        zoom = _calculate_zoom_factor(clip_time, segments, enabled=zoom_enabled, zoom_scale=1.15)

        is_solo = False
        solo_spk = 0
        if solo_windows:
            for (w_start, w_end, spk) in solo_windows:
                if w_start <= clip_time < w_end:
                    is_solo = True
                    solo_spk = spk
                    break

        if layout_type == "split_vertical":
            shot_is_solo = (solo_mask is not None and frame_idx - 1 < len(solo_mask) and solo_mask[frame_idx - 1])
            if shot_is_solo:
                is_solo = True
                s_cx, s_cy = solo_traj[frame_idx - 1] if (solo_traj and frame_idx - 1 < len(solo_traj)) else (default_cx, default_cy)
                composed = _render_full_bleed_canvas(frame, src_w, src_h, s_cx, s_cy, zoom=zoom)
            elif is_solo:
                # Dynamic Full-Bleed 9:16 solo of the verified active speaking host
                if traj_left is not None and traj_right is not None:
                    cx_l, cy_l = traj_left[frame_idx - 1] if frame_idx - 1 < len(traj_left) else (default_cx, default_cy)
                    cx_r, cy_r = traj_right[frame_idx - 1] if frame_idx - 1 < len(traj_right) else (default_cx, default_cy)
                else:
                    cx_l, cy_l = src_w // 4, src_h // 2
                    cx_r, cy_r = src_w * 3 // 4, src_h // 2
                solo_cx, solo_cy = (cx_l, cy_l) if solo_spk == 0 else (cx_r, cy_r)
                half = "left" if solo_spk == 0 else "right"
                composed = _render_full_bleed_canvas(frame, src_w, src_h, solo_cx, solo_cy, zoom=zoom, clamp_half=half)
            else:
                # Medium-Bust (chest-up) dual split screen with locked anchors
                if traj_left is not None and traj_right is not None:
                    cx_l, cy_l = traj_left[frame_idx - 1] if frame_idx - 1 < len(traj_left) else (default_cx, default_cy)
                    cx_r, cy_r = traj_right[frame_idx - 1] if frame_idx - 1 < len(traj_right) else (default_cx, default_cy)
                else:
                    cx_l, cy_l = src_w // 4, src_h // 2
                    cx_r, cy_r = src_w * 3 // 4, src_h // 2
                composed = _render_podcast_canvas(frame, src_w, src_h, cx_l, cy_l, cx_r, cy_r, crop_scale=bust_scale)
        elif layout_type == "blurred_backdrop" or use_blur:
            composed = _render_blurred_backdrop_canvas(frame, src_w, src_h, default_cx, default_cy, zoom=zoom)
        elif layout_type == "single_focus":
            cx, cy = trajectory[frame_idx - 1] if frame_idx - 1 < len(trajectory) else (default_cx, default_cy)
            composed = _render_stage_canvas(frame, src_w, src_h, cx, cy, zoom=zoom)
        else:
            if trajectory is not None:
                cx, cy = trajectory[frame_idx - 1] if frame_idx - 1 < len(trajectory) else (default_cx, default_cy)
            else:
                cx, cy = default_cx, default_cy
            composed = _render_full_bleed_canvas(frame, src_w, src_h, cx, cy, zoom=zoom)

        # Apply visual enhancement filter (Vivid Pop, Warm Studio, Clean Crisp, etc.)
        if video_filter and video_filter != "none":
            composed = apply_video_filter(composed, video_filter)

        composed = _decorate_frame(
            composed,
            spec,
            frame_idx,
            total_frames,
            pct,
            time=clip_time,
            segments=segments,
            style=style,
            branding=branding,
            is_solo=is_solo,
        )
        writer.write(composed)

        if progress is not None:
            if getattr(progress, "is_cancelled", False) or (callable(getattr(progress, "check_cancelled", None)) and progress.check_cancelled()):
                cap.release()
                writer.release()
                if os.path.exists(silent_path):
                    try:
                        os.remove(silent_path)
                    except Exception:
                        pass
                _cleanup_temp(temp_path, orig_path)
                raise InterruptedError("Render cancelled by user.")
            if (frame_idx % 30 == 0 or total_frames == 0) and hasattr(progress, "update"):
                progress.update(frame_idx)

    cap.release()
    writer.release()
    del cap, writer
    gc.collect()

    master_audio = bool(style.get("master_audio", True)) if style else True
    _mux_audio(silent_path, out_path, source_path, start_time, end_time, in_path, master_audio=master_audio)
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
    *burn_captions* controls subtitle burning: set to True to render
    word-by-word subtitles into the frame pixels.
    """
    if not burn_captions:
        # Clean output: omit burned captions
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
    *burn_captions*: set to True to burn word-by-word captions into the rendered frames.
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

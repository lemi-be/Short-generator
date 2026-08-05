"""Per-clip cropping via MuAPI /autocrop.

Given the source video URL plus a highlight's start/end, MuAPI returns a
vertically-cropped 9:16 short ready for posting.
"""
from typing import Dict

from . import muapi
from .downloader import _extract_video_url

ASPECT_RATIO = "9:16"


def crop_clip(source_video_url: str, start_time: float, end_time: float) -> str:
    """Submit one autocrop job and return the URL of the rendered short."""
    payload = {
        "video_url": source_video_url,
        "start_time": float(start_time),
        "end_time": float(end_time),
        "aspect_ratio": ASPECT_RATIO,
    }
    print(f"[clip] {start_time:.1f}s -> {end_time:.1f}s @ {ASPECT_RATIO}", flush=True)
    result = muapi.run("autocrop", payload, label=f"autocrop({start_time:.0f}-{end_time:.0f})")
    return _extract_video_url(result)


def crop_highlights(source_video_url: str, highlights: list) -> list:
    """Crop every highlight, attaching the resulting URL back onto the dict."""
    out = []
    for i, h in enumerate(highlights, 1):
        print(f"[clip] {i}/{len(highlights)}: {h.get('title', '(untitled)')}", flush=True)
        try:
            url = crop_clip(
                source_video_url,
                h["start_time"],
                h["end_time"],
            )
            out.append({**h, "clip_url": url})
        except Exception as e:
            print(f"[clip] {i} failed: {e}", flush=True)
            out.append({**h, "clip_url": None, "error": str(e)})
    return out

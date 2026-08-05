"""End-to-end orchestrator.

Two modes:
  * mode="local" (default) — yt-dlp + faster-whisper + OpenAI or Gemini + ffmpeg/opencv.
                              Self-hosted, LLM_PROVIDER selects OpenAI or Gemini.
  * mode="api"              — MuAPI does download / transcribe / LLM / autocrop.
                              Kept for reference. Pay-per-call, no local deps.
"""
from typing import Dict, List, Optional

from .clipper import crop_highlights
from .downloader import download_youtube
from .highlights import call_muapi_llm, get_highlights
from .transcriber import transcribe


def _run_local(
    youtube_url: str,
    num_clips: int,
    download_format: str,
    language: Optional[str],
    min_clip_seconds: int,
    max_clip_seconds: int,
    template: Optional[str] = None,
) -> Dict:
    from .local.clipper import DEFAULT_TEMPLATE, TEMPLATE_LABELS, crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_local_llm
    from .local.transcriber import transcribe_local

    from .progress import stage

    stage(1, 4, "Downloading source video")
    source_path = download_youtube_local(youtube_url, fmt=download_format)

    stage(2, 4, "Transcribing audio with Whisper")
    transcript = transcribe_local(source_path, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    stage(3, 4, f"Ranking highlights (target: top {num_clips}, 30-{max_clip_seconds}s each)")
    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_local_llm,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]

    label = TEMPLATE_LABELS.get(template or DEFAULT_TEMPLATE, "Stage & Solo Speaker")
    stage(4, 4, f"Cropping {len(top)} vertical shorts ({label})")
    shorts = crop_highlights_local(source_path, top, template=template, transcript=transcript)

    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "template": template or DEFAULT_TEMPLATE,
    }


def _run_api(
    youtube_url: str,
    num_clips: int,
    download_format: str,
    language: Optional[str],
    min_clip_seconds: int,
    max_clip_seconds: int,
) -> Dict:
    source_url = download_youtube(youtube_url, fmt=download_format)

    transcript = transcribe(source_url, language=language)
    if not transcript["segments"]:
        raise RuntimeError(
            "Whisper produced no segments. The video may have no detectable speech."
        )

    highlights_result = get_highlights(
        transcript,
        num_clips=num_clips,
        llm_fn=call_muapi_llm,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
    )
    all_highlights: List[Dict] = highlights_result.get("highlights", [])
    if not all_highlights:
        raise RuntimeError("Highlight generator returned zero clips.")

    top = sorted(all_highlights, key=lambda h: int(h.get("score", 0)), reverse=True)[:num_clips]
    print(f"[pipeline] cropping {len(top)} of {len(all_highlights)} candidates", flush=True)

    shorts = crop_highlights(source_url, top)

    return {
        "mode": "api",
        "source_video_url": source_url,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 10,
    download_format: str = "720",
    language: Optional[str] = None,
    mode: str = "local",
    min_clip_seconds: int = 30,
    max_clip_seconds: int = 60,
    template: Optional[str] = None,
) -> Dict:
    """Run the full pipeline and return a structured result.

    Args:
        youtube_url: source URL.
        num_clips: how many shorts to render.
        download_format: source resolution ("360" / "480" / "720" / "1080").
        language: ISO-639-1 to force Whisper language detection.
        mode: "local" (default, yt-dlp + faster-whisper + OpenAI or Gemini +
            ffmpeg) or "api" (MuAPI, kept for reference).
        min_clip_seconds: drop highlights shorter than this (default 30).
        max_clip_seconds: clamp highlights longer than this (default 60).
        template: cropping template key (see TEMPLATE_SPECS in clipper.py).
            Defaults to stage_solo_speaker.

    Returns:
        {
          "mode": "api" | "local",
          "source_video_url": str,   # hosted URL (api) or local path (local)
          "transcript": {...},
          "highlights": [...],       # all candidates ranked
          "shorts": [...],           # top `num_clips` with clip_url / local path
        }
    """
    mode = (mode or "local").lower()
    if mode == "local":
        return _run_local(
            youtube_url, num_clips, download_format, language,
            min_clip_seconds, max_clip_seconds, template=template,
        )
    if mode == "api":
        return _run_api(
            youtube_url, num_clips, download_format, language,
            min_clip_seconds, max_clip_seconds,
        )
    raise ValueError(f"Unknown mode: {mode!r}. Use 'api' or 'local'.")

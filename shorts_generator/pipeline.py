"""End-to-end orchestrator for local shorts generation.

Pipeline stages:
  1. yt-dlp source video download (or local file resolution)
  2. faster-whisper local audio transcription with word-level timestamps
  3. LLM highlight detection and ranking (OpenAI, Gemini, or Ollama)
  4. ffmpeg + OpenCV vertical reframing, face-tracking, and clip rendering
"""
from typing import Dict, List, Optional

from .highlights import get_highlights


def _run_local(
    youtube_url: str,
    num_clips: int,
    download_format: str,
    language: Optional[str],
    min_clip_seconds: int,
    max_clip_seconds: int,
    template: Optional[str] = None,
    burn_captions: bool = False,
    cookies_path: Optional[str] = None,
) -> Dict:
    from .local.clipper import DEFAULT_TEMPLATE, TEMPLATE_LABELS, crop_highlights_local
    from .local.downloader import download_youtube_local
    from .local.llm import call_local_llm
    from .local.transcriber import transcribe_local
    from .progress import Progress, stage

    stage(1, 4, "Downloading source video")
    source_path = download_youtube_local(youtube_url, fmt=download_format, cookies_path=cookies_path)

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
    shorts = crop_highlights_local(
        source_path,
        top,
        template=template,
        transcript=transcript,
        burn_captions=burn_captions,
    )

    return {
        "mode": "local",
        "source_video_url": source_path,
        "transcript": transcript,
        "highlights": all_highlights,
        "shorts": shorts,
        "template": template or DEFAULT_TEMPLATE,
    }


def generate_shorts(
    youtube_url: str,
    num_clips: int = 10,
    download_format: str = "1080",
    language: Optional[str] = None,
    mode: str = "local",
    min_clip_seconds: int = 30,
    max_clip_seconds: int = 60,
    template: Optional[str] = None,
    burn_captions: bool = False,
    cookies_path: Optional[str] = None,
) -> Dict:
    """Run the local pipeline and return a structured result.

    Args:
        youtube_url: source URL or local video path.
        num_clips: how many shorts to render.
        download_format: source resolution ("360" / "480" / "720" / "1080" / "best").
        language: ISO-639-1 to force Whisper language detection.
        mode: pipeline execution mode (always "local").
        min_clip_seconds: drop highlights shorter than this (default 30).
        max_clip_seconds: clamp highlights longer than this (default 60).
        template: cropping template key (e.g. "full_bleed_solo", "split_screen").
        burn_captions: when True, burn word-by-word captions into rendered frames.
        cookies_path: optional path to a cookies.txt file for YouTube authentication.

    Returns:
        {
          "mode": "local",
          "source_video_url": str,   # local path
          "transcript": {...},
          "highlights": [...],       # all candidates ranked
          "shorts": [...],           # top `num_clips` with local path
        }
    """
    mode = (mode or "local").lower()
    if mode != "local":
        raise ValueError(f"Unsupported mode: {mode!r}. Only 'local' mode is supported.")

    return _run_local(
        youtube_url,
        num_clips,
        download_format,
        language,
        min_clip_seconds,
        max_clip_seconds,
        template=template,
        burn_captions=burn_captions,
        cookies_path=cookies_path,
    )

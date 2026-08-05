"""Transcription via MuAPI /openai-whisper.

Sends a hosted media URL to MuAPI's Whisper endpoint and returns the segment
shape expected by the highlight generator: {duration, segments[start,end,text]}.
The API runs verbose_json server-side, so we get per-segment timestamps for free.
"""
import json
from typing import Dict, Optional

from . import muapi


def _coerce_verbose(raw) -> Dict:
    """The /openai-whisper result can land as a dict or a JSON string depending on
    how the worker stored it. Normalise to a dict with `duration` and `segments`."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_verbose_payload(result: Dict) -> Dict:
    """MuAPI wraps results inconsistently across endpoints. Hunt for the
    verbose_json blob (which has `segments` + `duration`)."""
    
    # Check for error status first
    status = result.get("status", "").lower()
    if status in ("failed", "error"):
        error_msg = result.get("error") or result.get("message") or "Unknown error"
        raise RuntimeError(f"Whisper transcription failed with status '{status}': {error_msg}")
    
    # If outputs exist but are empty, that means transcription ran but found no speech
    outputs = result.get("outputs")
    if isinstance(outputs, list) and len(outputs) == 0:
        raise RuntimeError(
            f"Whisper produced no output (empty segments). The video may have:\n"
            f"  - No detectable speech\n"
            f"  - Only music/background noise\n"
            f"  - Audio in an unsupported language\n"
            f"Response: {result}"
        )
    
    for key in ("output", "result", "outputs"):
        v = result.get(key)
        if isinstance(v, dict) and "segments" in v:
            return v
        if isinstance(v, list) and v:
            first = v[0]
            decoded = _coerce_verbose(first)
            if "segments" in decoded:
                return decoded
        if isinstance(v, str):
            decoded = _coerce_verbose(v)
            if "segments" in decoded:
                return decoded

    if "segments" in result:
        return result

    raise RuntimeError(
        f"Could not find Whisper segments in MuAPI response.\n"
        f"Expected 'segments' key in output/result/outputs, but got: {result}"
    )


def transcribe(media_url: str, language: Optional[str] = None) -> Dict:
    """Run MuAPI /openai-whisper on a hosted media URL.

    Returns {duration: float, segments: [{start, end, text}, ...]} so it slots
    straight into the highlight generator.
    """
    print(f"[transcribe] muapi /openai-whisper on {media_url}", flush=True)
    payload = {
        "audio_url": media_url,
        "response_format": "verbose_json",
    }
    if language:
        payload["language"] = language

    result = muapi.run("openai-whisper", payload, label="openai-whisper")
    verbose = _extract_verbose_payload(result)

    segments = []
    for s in verbose.get("segments") or []:
        segments.append({
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("end", 0.0)),
            "text": (s.get("text") or "").strip(),
        })

    duration = float(verbose.get("duration") or (segments[-1]["end"] if segments else 0.0))
    print(f"[transcribe] {len(segments)} segments, {duration:.0f}s of audio", flush=True)
    return {"duration": duration, "segments": segments}

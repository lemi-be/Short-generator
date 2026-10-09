"""Find the most viral-worthy highlights in a transcript.

Logic ported from ViralVadoo's transcript_analysis/highlight_generator.py:
  - content-type / density detection
  - chunking for long videos with overlap
  - virality-criteria prompt
  - score-based dedupe with overlap suppression

The LLM call is pluggable via the `llm_fn` argument so the same prompts can
drive either a direct local LLM client (default, --mode local) or MuAPI
(--mode api, kept for reference).
"""
import json
import re
from typing import Callable, Dict, List, Optional

from .progress import Progress


LLMFn = Callable[[str], str]


def _default_llm_fn(prompt: str) -> str:
    from .local.llm import call_local_llm
    return call_local_llm(prompt)


CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""


VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...", "I was completely wrong about...")
2. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that trigger agree/disagree
4. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks
5. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
6. QUOTABLE ONE-LINERS — a sentence that works as a standalone quote card
7. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
8. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply
"""


HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video editor who has studied thousands of viral clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript. These will be cropped into vertical 9:16 shorts, so every second has to earn its place.

Rules:
- HARD DURATION CAP: each highlight must be between 30 and 60 seconds. Never shorter than 30s, never longer than 60s. Pick the tightest window that contains the full hook-to-payoff arc.
- Every highlight must open with a strong HOOK — a line that grabs attention within the first 3 seconds. Lead with the strongest line in the window; do not start at a low-energy setup.
- Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained (start and end on a natural sentence boundary).
- Clips must not overlap with each other.
- Score 0-100 on viral potential (not general quality). Bias toward moments that stop the scroll, not moments that are merely interesting.
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — the opening line that would make someone stop scrolling. It must be the literal first line of the clip.
- Explain in one sentence why this clip is viral ("virality_reason").

Respond ONLY with valid JSON (no markdown, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"score":int,"hook_sentence":"string","virality_reason":"string"}}]}}"""


CHUNK_SIZE_SECONDS = 600       # 10-min chunks for long videos (20 min was too large; the LLM's JSON output degrades with 400+ transcript lines)
LONG_VIDEO_THRESHOLD = 1800     # chunk videos longer than 30 min
CHUNK_OVERLAP_SECONDS = 60
GPT_CALL_TIMEOUT_SECONDS = 300  # cap LLM polls at 5 min — a wedged call should fail fast
MAX_HIGHLIGHT_API_ATTEMPTS = 3

# Hard length cap for any rendered short. The LLM is also told to stay
# inside this window, but we clamp again here so a model that returns a
# 90s clip is truncated, not rendered.
MIN_CLIP_SECONDS = 30
MAX_CLIP_SECONDS = 60




def _parse_json_loose(raw: str) -> Dict:
    """gpt-5-4 sometimes wraps JSON in markdown fences — strip and parse."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])
        raise


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sanitize_highlights(
    raw_highlights: object,
    duration: float,
    min_seconds: float = MIN_CLIP_SECONDS,
    max_seconds: float = MAX_CLIP_SECONDS,
) -> List[Dict]:
    """Normalize model output into the expected shape; skip invalid entries.

    Hard cap: every clip is clamped to [min_seconds, max_seconds]. The LLM
    is told to stay inside the window, but we re-clamp here so any clip the
    model returns that's too long is truncated to max_seconds, and any clip
    that's too short is dropped (videos that can't sustain 30s of
    engagement don't perform on short-form feeds).
    """
    if not isinstance(raw_highlights, list):
        return []

    max_end = duration if duration > 0 else float("inf")
    cleaned: List[Dict] = []
    for item in raw_highlights:
        if not isinstance(item, dict):
            continue

        start = _coerce_float(item.get("start_time"), default=-1.0)
        end = _coerce_float(item.get("end_time"), default=-1.0)
        if start < 0 or end <= start:
            continue

        if max_end != float("inf"):
            start = min(start, max_end)
            end = min(end, max_end)
            if end <= start:
                continue

        # Enforce [min_seconds, max_seconds] window. Truncate from the right
        # (drop the tail of the clip) so the hook line at start_time is
        # preserved.
        if end - start > max_seconds:
            end = start + max_seconds
        if end - start < min_seconds:
            continue

        cleaned.append(
            {
                "title": str(item.get("title") or "Untitled Highlight").strip(),
                "start_time": start,
                "end_time": end,
                "score": max(0, min(100, _coerce_int(item.get("score"), default=0))),
                "hook_sentence": str(item.get("hook_sentence") or "").strip(),
                "virality_reason": str(item.get("virality_reason") or "").strip(),
            }
        )

    return cleaned


def detect_content_type(transcript: Dict, llm_fn: Optional[LLMFn] = None) -> Dict[str, str]:
    fn = llm_fn or _default_llm_fn
    segments = transcript.get("segments", [])
    sample = " ".join(s["text"] for s in segments[:25])[:3000]
    prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
    try:
        raw = fn(prompt)
        return _parse_json_loose(raw)
    except Exception:
        return {"content_type": "other", "density": "medium"}


def build_transcript_text(transcript: Dict) -> str:
    segments = transcript.get("segments", [])
    return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segments)


def chunk_transcript(transcript: Dict) -> List[Dict]:
    segments = transcript.get("segments", [])
    duration = transcript.get("duration", segments[-1]["end"] if segments else 0)
    chunks = []
    start = 0
    while start < duration:
        end = min(start + CHUNK_SIZE_SECONDS, duration)
        chunk_segs = [
            s for s in segments
            if s["start"] >= start and s["end"] <= end + CHUNK_OVERLAP_SECONDS
        ]
        if chunk_segs:
            chunk = dict(transcript)
            chunk["segments"] = chunk_segs
            chunk["duration"] = end - start
            chunk["_offset"] = start
            chunks.append(chunk)
        start += CHUNK_SIZE_SECONDS - CHUNK_OVERLAP_SECONDS
    return chunks


def call_highlight_api(
    transcript_text: str,
    content_info: Dict,
    duration: float,
    num_clips: int,
    is_chunk: bool = False,
    llm_fn: Optional[LLMFn] = None,
    min_clip_seconds: float = MIN_CLIP_SECONDS,
    max_clip_seconds: float = MAX_CLIP_SECONDS,
) -> Dict:
    fn = llm_fn or _default_llm_fn
    # Ask for ~2× the user's target so dedupe has headroom, but cap so the model
    # doesn't have to generate a huge JSON payload (which times out the LLM).
    target = max(num_clips * 2, 5)
    natural_max = max(2 if is_chunk else 3, int(duration / 90))
    min_clips = min(target, natural_max, 8)
    system = HIGHLIGHT_SYSTEM_PROMPT.format(
        virality_criteria=VIRALITY_CRITERIA,
        content_type=content_info.get("content_type", "other"),
        density=content_info.get("density", "medium"),
        num_clips_instruction=f"Generate at least {min_clips} highlights",
    )
    base_prompt = f"{system}\n\nTranscript:\n{transcript_text}"
    prompt = base_prompt
    last_error = "unknown"

    for attempt in range(1, MAX_HIGHLIGHT_API_ATTEMPTS + 1):
        raw = fn(prompt)
        try:
            parsed = _parse_json_loose(raw)
            highlights = _sanitize_highlights(
                parsed.get("highlights"),
                duration=duration,
                min_seconds=min_clip_seconds,
                max_seconds=max_clip_seconds,
            )
            if highlights:
                return {"highlights": highlights}
            last_error = "no valid highlights in response"
        except Exception as e:
            last_error = str(e)

        if attempt < MAX_HIGHLIGHT_API_ATTEMPTS:
            print(
                f"[highlights] invalid model output on attempt {attempt}/{MAX_HIGHLIGHT_API_ATTEMPTS}; retrying",
                flush=True,
            )
            prompt = (
                base_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON with a top-level 'highlights' array."
                + " Each item must include: title, start_time, end_time, score, hook_sentence, virality_reason."
                + " No markdown fences, no commentary."
                + "\n\nEXAMPLE:\n"
                + '{"highlights":[{"title":"The Hook","start_time":420.0,"end_time":460.0,"score":95,"hook_sentence":"Nobody talks about this...","virality_reason":"Creates immediate curiosity with a bold claim."}]}'
            )

    raise RuntimeError(
        f"Highlight generator produced invalid output after {MAX_HIGHLIGHT_API_ATTEMPTS} attempts: {last_error}"
    )


def dedupe_highlights(highlights: List[Dict]) -> List[Dict]:
    """Drop a highlight if it overlaps >50% with a higher-scoring one already kept."""
    highlights = sorted(highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    kept: List[Dict] = []
    for h in highlights:
        h_start = float(h["start_time"])
        h_end = float(h["end_time"])
        h_dur = h_end - h_start
        overlapping = False
        for k in kept:
            latest_start = max(h_start, float(k["start_time"]))
            earliest_end = min(h_end, float(k["end_time"]))
            overlap = earliest_end - latest_start
            if overlap > 0 and overlap > 0.5 * h_dur:
                overlapping = True
                break
        if not overlapping:
            kept.append(h)
    return kept


def get_highlights(
    transcript: Dict,
    num_clips: int = 10,
    llm_fn: Optional[LLMFn] = None,
    min_clip_seconds: float = MIN_CLIP_SECONDS,
    max_clip_seconds: float = MAX_CLIP_SECONDS,
) -> Dict:
    """Main entry point — returns {highlights: [...]} sorted by score.

    `llm_fn` swaps the underlying LLM. Defaults to the configured local LLM
    (OpenAI, Gemini, or Ollama).
    """
    llm_fn = llm_fn or _default_llm_fn
    duration = transcript.get("duration", 0)
    print(f"[highlights] detecting content type...", flush=True)
    with Progress("Detecting content type", total=None):
        content_info = detect_content_type(transcript, llm_fn=llm_fn)
    print(f"[highlights] content={content_info.get('content_type')} density={content_info.get('density')} duration={duration:.0f}s", flush=True)

    if duration >= LONG_VIDEO_THRESHOLD:
        chunks = chunk_transcript(transcript)
        print(f"[highlights] long video — splitting into {len(chunks)} chunks", flush=True)
        all_highlights: List[Dict] = []
        chunk_failures = 0
        p = Progress(
            f"Ranking highlights (long video, {len(chunks)} chunks)",
            total=len(chunks),
        )
        p.__enter__()
        try:
            for i, chunk in enumerate(chunks):
                offset = chunk.get("_offset", 0)
                text = build_transcript_text(chunk)
                print(f"[highlights] chunk {i + 1}/{len(chunks)} (offset {offset:.0f}s)", flush=True)
                try:
                    result = call_highlight_api(
                        text,
                        content_info,
                        chunk["duration"],
                        num_clips=num_clips,
                        is_chunk=True,
                        llm_fn=llm_fn,
                        min_clip_seconds=min_clip_seconds,
                        max_clip_seconds=max_clip_seconds,
                    )
                    for h in result.get("highlights", []):
                        h["start_time"] = float(h["start_time"]) + offset
                        h["end_time"] = float(h["end_time"]) + offset
                        all_highlights.append(h)
                except Exception as e:
                    chunk_failures += 1
                    print(
                        f"  [!] chunk {i + 1} failed, skipping: {e}",
                        flush=True,
                    )
                p.update(i + 1)
        except Exception as e:
            p.fail(str(e))
            raise

        if not all_highlights:
            p.fail("all chunks failed — no highlights found")
        else:
            skipped = f" ({len(chunks) - chunk_failures}/{len(chunks)} chunks)" if chunk_failures else ""
            p.finish(f"{len(all_highlights)} highlights{skipped}")
        highlights = dedupe_highlights(all_highlights)
    else:
        text = build_transcript_text(transcript)
        with Progress("Ranking highlights", total=None):
            result = call_highlight_api(
                text,
                content_info,
                duration,
                num_clips=num_clips,
                llm_fn=llm_fn,
                min_clip_seconds=min_clip_seconds,
                max_clip_seconds=max_clip_seconds,
            )
        highlights = dedupe_highlights(result.get("highlights", []))

    print(f"[highlights] {len(highlights)} candidates after dedupe", flush=True)
    return {"highlights": highlights}

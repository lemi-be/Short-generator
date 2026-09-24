"""Sentence-boundary alignment and re-segmentation for transcripts.

Ensures that every segment in the transcription starts on the first word of a
sentence (after a full stop/terminal punctuation) and ends cleanly on the final
word containing the full stop (., ?, !). This guarantees clean in/out cut points
when marking clips.
"""
import re
from typing import Any, Dict, List, Union

ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.",
    "e.g.", "i.e.", "u.s.", "inc.", "ltd.", "co.", "st.", "approx.", "dept.",
    "gov.", "gen.", "sen.", "rep.", "pres."
}


def is_sentence_end(word_text: str) -> bool:
    """Return True if word ends with terminal punctuation (. ? !) and is not an abbreviation."""
    if not word_text:
        return False
    clean = word_text.strip().lower()
    clean_stripped = re.sub(r"^[^\w]+|[^\w.]+$", "", clean)
    if clean_stripped in ABBREVIATIONS:
        return False
    # Check for terminal punctuation (., ?, !), optionally followed by quotes or brackets
    return bool(re.search(r'[.?!][\"\'\)\]”’]*$', word_text.strip()))


def extract_words(data: Any) -> List[Dict[str, Any]]:
    """Extract a flattened chronological list of word dicts from segments, blocks, or word lists."""
    words: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        # Could be {"segments": [...]}
        data = data.get("segments", [])
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                if "words" in item and isinstance(item["words"], list):
                    words.extend(item["words"])
                elif "word" in item:
                    words.append(item)
                elif "text" in item and "start" in item and "end" in item:
                    # Segment without explicit words: treat as a unit
                    words.append({
                        "start": float(item.get("start", 0.0)),
                        "end": float(item.get("end", 0.0)),
                        "word": str(item.get("text", "")).strip(),
                    })
            elif isinstance(item, list):
                # Nested list of words, like words.json
                for sub in item:
                    if isinstance(sub, dict):
                        words.append(sub)
    return words


def resegment_by_sentences(
    data: Any,
    min_words: int = 2,
    min_duration: float = 0.8,
    pause_threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """Group words into clean sentence-aligned segments.

    Option B (Natural Grouping):
    - Every segment starts on the first word of a sentence.
    - Every segment ends precisely on a full stop / terminal punctuation (. ? !).
    - Sentences with at least `min_words` and `min_duration` (or followed by a
      pause >= `pause_threshold`) form individual segments.
    - Extremely short 1-word utterances without a pause are kept with the adjacent
      sentence so breaks don't clutter the editor with tiny fragments.
    """
    words = extract_words(data)
    if not words:
        # Fallback if no words can be extracted
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "segments" in data:
            return data["segments"]
        return []

    segments: List[Dict[str, Any]] = []
    curr_words: List[Dict[str, Any]] = []

    for i, w in enumerate(words):
        curr_words.append(w)
        next_w = words[i + 1] if i + 1 < len(words) else None
        w_text = str(w.get("word", w.get("text", ""))).strip()

        if is_sentence_end(w_text):
            dur = float(curr_words[-1].get("end", 0.0)) - float(curr_words[0].get("start", 0.0))
            word_count = len(curr_words)
            pause = (float(next_w.get("start", 0.0)) - float(w.get("end", 0.0))) if next_w else 0.0

            if next_w is None or (word_count >= min_words and dur >= min_duration) or pause >= pause_threshold:
                seg_text = " ".join(
                    str(cw.get("word", cw.get("text", ""))).strip()
                    for cw in curr_words
                    if str(cw.get("word", cw.get("text", ""))).strip()
                )
                seg_text = re.sub(r"\s+", " ", seg_text).strip()
                segments.append({
                    "start": float(curr_words[0].get("start", 0.0)),
                    "end": float(curr_words[-1].get("end", 0.0)),
                    "text": seg_text,
                    "words": list(curr_words),
                })
                curr_words = []

    if curr_words:
        seg_text = " ".join(
            str(cw.get("word", cw.get("text", ""))).strip()
            for cw in curr_words
            if str(cw.get("word", cw.get("text", ""))).strip()
        )
        seg_text = re.sub(r"\s+", " ", seg_text).strip()
        segments.append({
            "start": float(curr_words[0].get("start", 0.0)),
            "end": float(curr_words[-1].get("end", 0.0)),
            "text": seg_text,
            "words": list(curr_words),
        })

    return segments

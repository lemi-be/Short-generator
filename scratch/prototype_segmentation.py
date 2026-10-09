import json
import re
from pathlib import Path

def test_segmentation():
    words_file = Path("output/source_FYAOwgh95bs.words.json")
    if not words_file.exists():
        print("words file not found")
        return

    raw_blocks = json.loads(words_file.read_text(encoding="utf-8"))
    words = []
    for block in raw_blocks:
        if isinstance(block, list):
            for w in block:
                words.append(w)
        elif isinstance(block, dict):
            words.append(block)

    ABBREVIATIONS = {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.",
        "e.g.", "i.e.", "u.s.", "inc.", "ltd.", "co."
    }

    def is_sentence_end(word_text):
        clean = word_text.strip().lower()
        if clean in ABBREVIATIONS:
            return False
        # Match terminal punctuation .?! optionally followed by quotes
        return bool(re.search(r'[.?!][\"\'\)\]]?$', word_text.strip()))

    segments = []
    curr_words = []

    for i, w in enumerate(words):
        curr_words.append(w)
        next_w = words[i+1] if i + 1 < len(words) else None
        w_text = w.get("word", "")
        
        # Check if sentence end
        if is_sentence_end(w_text):
            dur = curr_words[-1]["end"] - curr_words[0]["start"]
            word_count = len(curr_words)
            pause = (next_w["start"] - w["end"]) if next_w else 0.0
            
            # Option B: Break if we have at least 2 words (e.g. 'I agree.', 'For sure.')
            # or if it's 1 word followed by a pause >= 0.5s, or end of speech
            if next_w is None or word_count >= 2 or pause >= 0.5:
                seg_text = " ".join(cw["word"].strip() for cw in curr_words if cw["word"].strip())
                segments.append({
                    "start": curr_words[0]["start"],
                    "end": curr_words[-1]["end"],
                    "text": seg_text,
                    "words": list(curr_words)
                })
                curr_words = []

    if curr_words:
        seg_text = " ".join(cw["word"].strip() for cw in curr_words if cw["word"].strip())
        segments.append({
            "start": curr_words[0]["start"],
            "end": curr_words[-1]["end"],
            "text": seg_text,
            "words": list(curr_words)
        })

    print(f"Total words: {len(words)}, total sentence-aligned segments: {len(segments)}")
    durs = [s["end"] - s["start"] for s in segments]
    print(f"Durations: Min={min(durs):.2f}s, Max={max(durs):.2f}s, Avg={sum(durs)/len(durs):.2f}s")
    print(f"Segments under 1.5s: {sum(1 for d in durs if d < 1.5)}")
    print(f"Segments between 1.5s and 8.0s: {sum(1 for d in durs if 1.5 <= d <= 8.0)}")
    print(f"Segments over 12.0s: {sum(1 for d in durs if d > 12.0)}")

    print("\n--- DETAILED WORDS IN 54s SEGMENT ---")
    for s in segments:
        dur = s["end"] - s["start"]
        if dur > 50:
            for w in s["words"]:
                if is_sentence_end(w["word"]):
                    print(f"End word: {w['word']!r}, start={w['start']:.2f}, end={w['end']:.2f}")

    print("\n--- CHECKING FOR CUTS IN MIDDLE OF SENTENCE ---")
    bad_ends = []
    for idx, s in enumerate(segments):
        t = s["text"].strip()
        if not re.search(r'[.?!][\"\'\)\]]?$', t):
            bad_ends.append((idx, t))
    if bad_ends:
        print(f"Found {len(bad_ends)} segments not ending with punctuation:")
        for b in bad_ends[:5]:
            print(b)
    else:
        print("PERFECT: 100% of segments end right at a full stop/terminal punctuation!")

if __name__ == "__main__":
    test_segmentation()

import json
import re
from pathlib import Path

ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", "etc.",
    "e.g.", "i.e.", "u.s.", "inc.", "ltd.", "co.", "st.", "approx.", "dept.",
    "gov.", "gen.", "sen.", "rep.", "pres."
}

def is_sentence_end(word_text: str) -> bool:
    clean = word_text.strip().lower()
    clean_stripped = re.sub(r'^[^\w]+|[^\w.]+$', '', clean)
    if clean_stripped in ABBREVIATIONS:
        return False
    return bool(re.search(r'[.?!][\"\'\)\]”’]*$', word_text.strip()))

def resegment_words(words, min_words=2, min_duration=0.8, pause_threshold=0.5):
    if not words:
        return []
    segments = []
    curr_words = []
    
    for i, w in enumerate(words):
        curr_words.append(w)
        next_w = words[i+1] if i + 1 < len(words) else None
        w_text = str(w.get("word", w.get("text", ""))).strip()
        
        if is_sentence_end(w_text):
            dur = float(curr_words[-1]["end"]) - float(curr_words[0]["start"])
            word_count = len(curr_words)
            pause = (float(next_w["start"]) - float(w["end"])) if next_w else 0.0
            
            if next_w is None or (word_count >= min_words and dur >= min_duration) or pause >= pause_threshold:
                seg_text = " ".join(str(cw.get("word", cw.get("text", ""))).strip() for cw in curr_words if str(cw.get("word", cw.get("text", ""))).strip())
                seg_text = re.sub(r"\s+", " ", seg_text).strip()
                segments.append({
                    "start": float(curr_words[0]["start"]),
                    "end": float(curr_words[-1]["end"]),
                    "text": seg_text,
                    "words": list(curr_words),
                })
                curr_words = []
                
    if curr_words:
        seg_text = " ".join(str(cw.get("word", cw.get("text", ""))).strip() for cw in curr_words if str(cw.get("word", cw.get("text", ""))).strip())
        seg_text = re.sub(r"\s+", " ", seg_text).strip()
        segments.append({
            "start": float(curr_words[0]["start"]),
            "end": float(curr_words[-1]["end"]),
            "text": seg_text,
            "words": list(curr_words),
        })
    return segments

def test_all_output():
    out_dir = Path("output")
    for f in sorted(out_dir.glob("source_*.words.json")):
        raw = json.loads(f.read_text(encoding="utf-8"))
        words = []
        for block in raw:
            if isinstance(block, list):
                words.extend(block)
            elif isinstance(block, dict):
                words.append(block)
        segs = resegment_words(words)
        bad = [s["text"] for s in segs if not is_sentence_end(s["text"])]
        print(f"{f.name}: {len(words)} words -> {len(segs)} segments. Non-terminal ends: {len(bad)} (at very end of file: {len(bad) == 1 and bad[0] == segs[-1]['text']})")

if __name__ == "__main__":
    test_all_output()

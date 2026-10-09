import json

with open("output/source_FYAOwgh95bs.words.json", "r", encoding="utf-8") as f:
    raw = json.load(f)
words = [w for b in raw for w in (b if isinstance(b, list) else [b])]
sub = [w for w in words if 2213 <= w["start"] <= 2268]
for i in range(len(sub)-1):
    gap = sub[i+1]["start"] - sub[i]["end"]
    if gap >= 0.4:
        print(f"Gap {gap:.2f}s after word {sub[i]['word']!r} at {sub[i]['end']:.2f}")

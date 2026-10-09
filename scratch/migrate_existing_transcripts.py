import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from shorts_generator.segmenter import resegment_by_sentences, is_sentence_end
from shorts_generator.local.transcriber import _format_srt_timestamp

def migrate_all_transcripts():
    output_dir = Path("output")
    srt_files = sorted(output_dir.glob("source_*.srt"))
    print(f"Found {len(srt_files)} SRT files in {output_dir}")

    migrated = 0
    for srt_path in srt_files:
        video_id = srt_path.stem.replace("source_", "", 1)
        words_path = output_dir / f"source_{video_id}.words.json"
        if not words_path.exists():
            print(f"Skipping {srt_path.name}: words.json not found")
            continue

        raw_words = json.loads(words_path.read_text(encoding="utf-8"))
        new_segments = resegment_by_sentences(raw_words)
        if not new_segments:
            print(f"Skipping {srt_path.name}: resegmentation returned no segments")
            continue

        # Write sentence-aligned SRT
        lines = []
        for idx, seg in enumerate(new_segments, start=1):
            start = _format_srt_timestamp(float(seg["start"]))
            end = _format_srt_timestamp(float(seg["end"]))
            text = str(seg.get("text", "")).strip().replace("\r", "").replace("\n", " ")
            lines.append(str(idx))
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        srt_path.write_text("\n".join(lines), encoding="utf-8")

        # Write sentence-aligned words.json
        words_by_segment = []
        for seg in new_segments:
            words_by_segment.append(
                [
                    {
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                        "word": str(w.get("word", "")),
                    }
                    for w in seg.get("words", [])
                ]
            )
        words_path.write_text(
            json.dumps(words_by_segment, ensure_ascii=False),
            encoding="utf-8",
        )
        migrated += 1
        print(f"Migrated {srt_path.name}: {len(new_segments)} sentence segments")

    print(f"\nSuccessfully migrated {migrated}/{len(srt_files)} transcripts to sentence-boundary alignment!")

if __name__ == "__main__":
    migrate_all_transcripts()

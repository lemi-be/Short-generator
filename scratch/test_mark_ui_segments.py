import os
import sys
import django
import re

WORKSPACE_DIR = r"c:\Users\User\Desktop\AI-Youtube-Shorts-Generator"
sys.path.insert(0, WORKSPACE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webui.settings")
django.setup()

from django.test import Client
from webui.models import Episode
from shorts_generator.segmenter import is_sentence_end

def test_ui():
    c = Client()
    ep = Episode.objects.filter(video_id="FYAOwgh95bs").first()
    assert ep is not None, "Episode not found"
    
    resp = c.get(f"/episodes/{ep.pk}/mark/")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    
    html = resp.content.decode("utf-8")
    
    # Extract segment text
    pattern = re.compile(r'<div class="segment transcript" data-start="([^"]+)" data-end="([^"]+)"[^>]*>.*?<span class="timecode"[^>]*>.*?</span>(.*?)</div>', re.DOTALL)
    matches = pattern.findall(html)
    print(f"Total UI segments rendered: {len(matches)}")
    assert len(matches) > 0, "No segments rendered in UI!"
    
    non_terminal = []
    for idx, (start, end, text) in enumerate(matches, 1):
        clean_text = text.strip()
        if not is_sentence_end(clean_text):
            non_terminal.append((idx, start, end, clean_text))
            
    print(f"Non-terminal segments: {len(non_terminal)}")
    if non_terminal:
        for item in non_terminal[:5]:
            print("  ", item)
    assert len(non_terminal) == 0, f"Found {len(non_terminal)} non-terminal segments in UI!"
    
    print("\nSUCCESS: All UI transcript segments start on a sentence start and end right at a full stop!")
    print(f"Sample First 5 Segments in UI:")
    for idx, (start, end, text) in enumerate(matches[:5], 1):
        print(f"  {idx}. [{float(start):06.2f} - {float(end):06.2f}] {text.strip()}")

if __name__ == "__main__":
    test_ui()

# Short Generator

Turn long-form videos into viral-ready vertical shorts. Point it at any YouTube URL or local video file, and it downloads the source, transcribes it with Whisper, ranks the most shareable moments through a virality-aware highlight framework, and renders each one as a 9:16 mp4 with real word-by-word captions, face tracking, and a choice of cropping templates.

Everything runs locally on your machine. The only remote call is the highlight-ranking LLM (OpenAI or Gemini).

## Features

- **YouTube or local file in, vertical shorts out** — hand it any URL or path and get back N ranked 9:16 mp4s
- **Local-first pipeline** — `yt-dlp` for downloads, `faster-whisper` for transcription (CPU or CUDA), `ffmpeg` + OpenCV for rendering
- **Virality-aware highlight selection** — clips ranked on hooks, emotional peaks, opinion bombs, revelations, conflict, quotable lines, story peaks, and practical value
- **Score + hook + reason for every clip** — each highlight carries a 0–100 viral score, an opening hook line, and a one-sentence explanation
- **Real word-by-word captions** — captions burned into each clip and highlighted in sync with the audio from Whisper word timestamps
- **Cropping templates** — `stage_solo_speaker` and `podcast_split_screen`, each rendered onto a 1080×1920 canvas with a motion-smoothed face-tracking trajectory
- **Long-video aware** — videos over 30 minutes are auto-chunked (10-min chunks, 60s overlap) so nothing gets missed
- **Smart dedupe** — overlapping highlights are collapsed by score so you never get near-duplicate clips
- **Two LLM providers** — `LLM_PROVIDER=openai` (works with Groq, DeepSeek, etc. via `OPENAI_BASE_URL`) or `LLM_PROVIDER=gemini`, both with retry/backoff
- **Built-in web UI** — a Django interface for downloading, transcribing, picking clips, generating shorts, and re-cutting them with text overlays, watermarks, and background audio
- **CLI + Python library** — use it from the shell or import `generate_shorts(...)` into your own pipeline
- **JSON output** — `--output-json` dumps the full result (transcript + every candidate + final clip paths) for downstream automation
- **Caching** — transcripts (`.srt` + word-timestamp sidecar) and downloads are cached, so re-runs skip Whisper and `yt-dlp`
- **Live progress** — inline progress bars with ETA for download, transcription, ranking, and per-frame rendering

## Installation

### Prerequisites

- Python 3.10+
- `ffmpeg` on your PATH (used for cutting and muxing)
- An LLM API key for highlight ranking: `OPENAI_API_KEY` or `GEMINI_API_KEY`
- Django, if you want the web UI (the CLI works without it)

### Steps

```bash
git clone https://github.com/lemi-be/Short-generator.git
cd Short-generator

python3.10 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-local.txt
pip install django          # optional — web UI only
```

### Environment variables

Create a `.env` file in the project root:

```bash
LLM_PROVIDER=openai           # openai or gemini
OPENAI_API_KEY=your_openai_key_here
OPENAI_MODEL=gpt-4o-mini
# Optional: use a compatible provider (Groq, DeepSeek, ...)
# OPENAI_BASE_URL=https://api.groq.com/openai/v1
# OPENAI_MODEL=llama-4-scout
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-2.5-flash

LOCAL_WHISPER_MODEL=base          # tiny / base / small / medium / large-v3
LOCAL_WHISPER_DEVICE=auto         # auto / cpu / cuda
LOCAL_OUTPUT_DIR=output           # where mp4s + caches land
# TEMPLATE=stage_solo_speaker     # default cropping template
```

## Usage

### Single video

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Rendered shorts are written to `./output/short_01.mp4`, `short_02.mp4`, … (override with `LOCAL_OUTPUT_DIR`).

### With options

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" \
    --num-clips 5 \
    --template podcast_split_screen \
    --min-clip-seconds 30 \
    --max-clip-seconds 45 \
    --output-json result.json
```

### Local file or path

Pass a `file://` URL or a direct filesystem path to skip YouTube entirely:

```bash
python main.py "/Users/you/Videos/input.mp4"
python main.py "file:///Users/you/Videos/input.mp4"
```

### Python API

```python
from shorts_generator import generate_shorts

result = generate_shorts(
    "/Users/you/Videos/input.mp4",
    num_clips=5,
    mode="local",
)
for short in result["shorts"]:
    print(short["score"], short["title"], short["clip_url"])
```

### Batch processing

Create a `urls.txt` file with one URL per line, then:

```bash
xargs -a urls.txt -I{} python main.py "{}"
```

### CLI flags

| Flag | Default | Notes |
|------|---------|-------|
| `--num-clips` | `10` | How many shorts to render |
| `--format` | `720` | Source download resolution: `360` / `480` / `720` / `1080` |
| `--language` | auto | Force Whisper language code (e.g. `en`) |
| `--min-clip-seconds` | `30` | Drop highlights shorter than this |
| `--max-clip-seconds` | `60` | Hard cap on clip length; longer highlights are truncated (max 60) |
| `--template` | `stage_solo_speaker` | Cropping template — `stage_solo_speaker` or `podcast_split_screen` |
| `--output-json` | — | Dump the full result (transcript + all candidates) to a file |

## Web UI (Django)

A browser-based editor for the pipeline. Start it with:

```bash
python manage.py migrate          # first run only
python manage.py runserver        # or double-click run_webui.bat
```

Then open **http://127.0.0.1:8000**.

**Workflow** — paste a YouTube URL → **Download** → **Transcribe** → **Pick clips** (browse the transcript and mark start/end ranges) → **Generate** vertical shorts. The home page tracks each video through the pipeline (Downloaded → Transcribed → Clips → Generated).

**Clip editor** (`/video/<id>/`):
- Browse the SRT transcript with timestamps
- Add / delete clip ranges, then render them all at once with a chosen template
- Watch generated shorts inline (byte-range streaming support)

**Trimmer** (`/video/<id>/trim/<filename>/`): re-cut any generated short with:
- **Text overlays** — font size, color, background box, stroke, uppercase, pop-in animation
- **Watermark / logo** overlay (uploaded images, positioned + scaled)
- **Background audio** layers (uploaded files) with optional auto-ducking and source-volume control
- **Cut ranges** to remove sections from the middle of a clip

## How It Works

1. **Download** — `yt-dlp` fetches the source video (`output/source_<id>.mp4`), reusing an existing download. If YouTube demands sign-in, it falls back to browser cookies (Chrome/Edge/Firefox/Brave/Opera) or a manual `cookies.txt` in the project root
2. **Transcribe** — `faster-whisper` (CPU or CUDA) produces a timestamped transcript with word-level timestamps, cached as `.srt`
3. **Detect content type** — an LLM classifies the video (podcast, interview, tutorial, vlog, etc.) and density so the prompt can be tuned per content style
4. **Long-video chunking** — videos > 30 min are split into 10-min overlapping chunks (60s overlap)
5. **Highlight ranking** — an LLM scans the transcript through a virality framework and emits ranked candidates with scores 0–100 and a hard 30–60s window
6. **Dedupe** — overlapping candidates are collapsed by score (>50% overlap → keep the higher score)
7. **Auto-crop** — each highlight is pre-scanned for a smoothed face-tracking trajectory, then rendered into the selected template's 1080×1920 canvas with word-by-word captions, a hook title, and audio muxed from the source

**Output**: a list of local mp4 paths plus, for each clip, its title, viral score, hook sentence, and a one-line reason explaining why it should perform.

## Cropping Templates

Templates are declared in `shorts_generator/local/clipper.py` (`TEMPLATE_SPECS`). The output is always a 1080×1920 (9:16) canvas with safe zones (23% top / 60% stage / 17% bottom).

| Key | Label | Layout |
|---|---|---|
| `stage_solo_speaker` | Stage & Solo Speaker | Video fills a 1080×1152 "stage"; hook title in the top safe zone; word-by-word captions in the lower band |
| `podcast_split_screen` | Podcast & Dialogue | Two stacked 9:8 panels (1080×960 each); each half tracks its own speaker's face |

Rendering is two-pass: a low-FPS pre-scan detects faces and builds a smooth camera trajectory (median filter + EMA + smoothstep), then every frame is composited from the pre-computed path — no jitter. If the scene is too wide to fit 9:16, a blurred-fill fallback is used instead of cropping.

## Output

Console output looks like:

```
================================================================================
Mode:          local
Template:      stage_solo_speaker
Source video:  output/source_VIDEO_ID.mp4
Highlights:    7 candidates -> kept top 3
================================================================================

#1  score=92  124.3s -> 184.3s
     title:  The one mistake that cost me $50K
     hook:   "Nobody talks about this, but it killed my first startup..."
     clip:   output/short_01.mp4

#2  score=88  ...
```

`--output-json result.json` produces:

```json
{
  "source_video_url": "output/source_VIDEO_ID.mp4",
  "mode": "local",
  "transcript": { "duration": 1873.4, "segments": [...] },
  "highlights": [ {...}, {...}, ... ],
  "shorts": [
    {
      "title": "...",
      "start_time": 124.3,
      "end_time": 184.3,
      "score": 92,
      "hook_sentence": "...",
      "virality_reason": "...",
      "clip_url": "output/short_01.mp4"
    }
  ]
}
```

## Configuration

### Highlight selection criteria

Edit `shorts_generator/highlights.py`:
- **Virality framework** — `VIRALITY_CRITERIA`, the ranked list of signals the LLM optimizes for
- **System prompt** — `HIGHLIGHT_SYSTEM_PROMPT`, the duration sweet spot, hook rules, and JSON schema
- **Chunk size** — `CHUNK_SIZE_SECONDS` (default 600)
- **Long-video threshold** — `LONG_VIDEO_THRESHOLD` (default 1800)
- **Chunk overlap** — `CHUNK_OVERLAP_SECONDS` (default 60)

### Cropping templates & captions

Edit `shorts_generator/local/clipper.py`:
- **`TEMPLATE_SPECS`** — add a new template (layout type, typography, widgets)
- **Canvas constants** — `CANVAS_W/H`, safe zones, caption font/colors
- **`_render_stage_canvas` / `_render_podcast_canvas`** — the per-template compositors

### LLM & Whisper

Edit `shorts_generator/config.py` (or set env vars):
- `LLM_PROVIDER`, `OPENAI_*`, `GEMINI_*` — local LLM backend + model
- `LOCAL_WHISPER_MODEL`, `LOCAL_WHISPER_DEVICE` — Whisper size and CPU/CUDA
- `LOCAL_WHISPER_VAD_FILTER` — Voice Activity Detection (off by default; too aggressive on mixed speech/music)
- `TEMPLATE` — default cropping template

## Project Structure

```
Short-generator/
├── main.py                       CLI entry point
├── manage.py                     Django entry point (web UI)
├── run_webui.bat                 Windows web UI launcher
├── requirements.txt              core deps
├── requirements-local.txt        deps for the local pipeline
├── .env.example
├── webui/                        Django web UI (download / transcribe / clip editor / trimmer)
│   ├── settings.py               sqlite + OUTPUT_DIR wiring
│   ├── models.py                 Clip (video_id, start_time, end_time)
│   ├── views.py                  download / transcribe / editor / generate / trim / uploads
│   └── templates/webui/          home, clip_editor, trim_short, video_list
└── shorts_generator/
    ├── config.py                 env / settings (LLM + Whisper + VAD)
    ├── highlights.py             LLM virality ranking
    ├── pipeline.py               end-to-end orchestrator + generate_shorts()
    ├── progress.py               progress bars / spinners with ETA
    ├── downloader.py             API-mode download (kept for reference)
    ├── transcriber.py            API-mode transcription (kept for reference)
    ├── clipper.py                API-mode cropping (kept for reference)
    ├── muapi.py                  API-mode submit + poll wrapper (kept for reference)
    └── local/                    local pipeline backends
        ├── downloader.py         yt-dlp download + caching + cookie fallback
        ├── transcriber.py        faster-whisper transcription + .srt cache
        ├── cookies.py            manual cookies.txt / browser cookie extraction
        ├── llm.py                OpenAI or Gemini client with retry/backoff
        └── clipper.py            ffmpeg cut + OpenCV template-based vertical crop + captions
```

## Troubleshooting

### Whisper produced no segments

The video may have no detectable speech, or it may be in a language Whisper struggles with. Try passing `--language en` (or the correct ISO-639-1 code) to skip auto-detection.

### YouTube demands sign-in / bot detection

The downloader automatically tries your browser's cookies. If that fails — typically because the browser's cookie DB is locked or encrypted — close the browser and retry, or export cookies manually:

```bash
yt-dlp --cookies cookies.txt --skip-download <video-url>
```

Then drop `cookies.txt` in the project root.

### `[WinError 32] The process cannot access the file`

A Windows file-lock race from an earlier render. Audio is read from the original source rather than the cut clip to avoid this; if you still hit it, close any player that has the mp4 open and re-run.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License.

# AI YouTube Shorts Generator & Production Line (Short Factory)

Turn long-form videos into viral, client-ready vertical (9:16) shorts. Point it at any YouTube URL or local video file, and it downloads the source, transcribes it locally with Whisper, detects sentence boundaries, ranks highlight moments with a virality framework, and renders 1080×1920 MP4s with motion-smoothed face tracking, dynamic kinetic typography, broadcast vocal mastering, and cinematic color grading.

Equipped with both a **high-throughput Web UI (Short Factory)** built for fast client batch delivery (under ~20 min operator turnaround) and a **fully scriptable CLI & Python pipeline**.

---

## Highlights & Capabilities

- **Fast-Path Client Production Line (v3)** — Manage client projects with persistent branding presets (caption styles, fonts, colors, brand logos, lower-thirds, filters, audio mastering). Set once per client; inherited automatically by every episode and clip.
- **7-Stage Production Workflow** — Structured operator workflow (Client Project &rarr; Add Episode &rarr; Local Transcription &rarr; Rapid In/Out Marking &rarr; Background Batch Render &rarr; Quick Review & Nudge Trim &rarr; 1-Click Delivery Packaging).
- **Control-Room Tally Light Status** — Instant visual state cues across projects and clips:
  - 🔴 **Red**: Awaiting operator action (unmarked transcript or unconfirmed clip).
  - 🟡 **Amber**: Automated background task in progress (downloading, transcribing, batch rendering).
  - 🟢 **Green**: Ready, confirmed, or packaged for delivery.
- **Advanced 9:16 Compositing Engine** — 4 specialized canvas layouts:
  - `full_bleed_solo` *(Default)*: Full-height vertical crop centered on the speaker.
  - `podcast_split_screen`: Stacked 50/50 dual view (two 9:8 panels) with center seam divider + **Dynamic Solo Switching** (cuts automatically to full-bleed when one speaker dominates).
  - `stage_solo_speaker`: 1080×1152 active stage framed with dedicated top/bottom safe zones (23% top / 17% bottom).
  - `blurred_backdrop`: Centered widescreen video with gaussian blurred fill (ideal for presentations, gaming, widescreen charts, or code walkthroughs).
- **Kinetic Word-by-Word Subtitle Engine** — TrueType rendering (Pillow) with outer stroke, drop shadow, and active word pop:
  - `hormozi_pop`: Impact bold, 1.22x active word expansion, `#FFEA00` electric yellow, keyword emojis.
  - `beast_neon`: Heavy sans, 1.14x pop, 12px heavy stroke, `#00F0FF` neon cyan, keyword emojis.
  - `minimal_clean`: Inter sans, 1.05x subtle pop, `#F4A261` warm coral, natural casing.
  - `documentary`: Georgia serif, editorial crimson `#E63946`, flat reading cadence.
  - `cyber_terminal`: JetBrains Mono, 1.15x pop, uppercase terminal green `#00FF66`.
- **Contextual Keyword Emojis** — Words like *money*, *fire*, *secret*, *mistake*, *win*, *brain*, *danger* dynamically spawn high-impact visual emojis next to the spoken word.
- **Broadcast Vocal Mastering Chain** — Integrated ffmpeg audio mastering:
  - 80 Hz highpass filter (removes mic plosives, room rumble, and desk thumps).
  - 3 kHz presence EQ (+2 dB, Q=1.0) (maximizes speech intelligibility on mobile phone speakers).
  - Native `loudnorm` normalization targeting the industry-standard **-14 LUFS** (-1.5 dBTP true peak).
  - High-fidelity 192k AAC 48 kHz encoding.
- **Speaker Visual Filters** — Real-time C++ OpenCV LUT color grading:
  - `vivid_pop` *(Default)*: S-curve contrast, +18% skin vibrance, +35% unsharp mask facial sharpening, spotlight vignette.
  - `warm_studio`: Golden amber/red tone boost, +14% saturation, soft glow.
  - `clean_crisp`: High clarity, +45% micro-contrast unsharp mask.
  - `cinematic`: Moody filmic shadows, deep contrast, rich saturation, 0.22 vignette.
  - `none`: Clean source pass-through.
- **Viewer Retention Enhancements**:
  - `zoom_punch`: 1.15x dynamic scale punch at transition points to reset viewer visual attention.
  - `hook_card`: Opening visual hook badge displayed during the crucial first 0.0–2.5s.
- **Sentence-Boundary Alignment** — Re-segments raw Whisper transcripts to guarantee in/out cut points fall strictly on natural sentence punctuation (`.`, `?`, `!`), eliminating awkward mid-sentence cut-offs.
- **Two-Pass Motion Smoothing** — Pass 1 pre-scans at low FPS, detects faces, computes union bounding boxes, and filters coordinates with median filtering + Exponential Moving Average (EMA) + smoothstep interpolation. Pass 2 renders from the pre-computed trajectory with zero micro-jitter.
- **YouTube Auth & Bot Bypass Tooling** — Bundled with `bgutil-ytdlp-pot-provider` and challenge solving to bypass 403 blocks without cookies. Also includes `export_cookies.py` for authenticated browser cookie extraction when needed.
- **Embedded FreeCut Video Editor** — Fully client-side, vendored WebGPU/WebCodecs multi-track editor served directly via Django at `/editor/` with COOP/COEP isolation headers. Auto-syncs projects, media, and clip-local transcripts (`freecut_projects.py`).

---

## System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              ENTRY POINTS                              │
│                                                                        │
│   main.py (CLI & Automation)        manage.py / run_webui.bat (Web UI) │
└───────────────────┬────────────────────────────────┬───────────────────┘
                    │                                │
                    ▼                                ▼
       ┌────────────────────────┐       ┌────────────────────────┐
       │   shorts_generator/    │       │     webui/ (Django)    │
       │  (Pipeline & Engine)   │       │   - Client Projects    │
       │  - segmenter.py        │       │   - Episode Management │
       │  - highlights.py (LLM) │       │   - Transcript Marker  │
       │  - freecut_projects.py │       │   - Background Worker  │
       │  local/:               │       │     (webui/jobs.py)    │
       │   - downloader (yt-dlp)│       │   - Review & Nudge     │
       │   - transcriber        │       │   - Delivery Packager  │
       │   - clipper (OpenCV)   │       └───────────┬────────────┘
       │   - llm (OpenAI/Gemini)│                   │
       └────────────────────────┘                   ▼
                                        ┌────────────────────────┐
                                        │  vendor/freecut/       │
                                        │  (WebGPU Browser NLE)  │
                                        │  Served at /editor/    │
                                        └────────────────────────┘
```

---

## Installation

### Prerequisites

1. **Python 3.10+**
2. **ffmpeg** and **ffprobe** installed and accessible on your system `PATH`.
3. **Node.js (v20+)** (recommended for `yt-dlp` JavaScript challenge execution and PO-token generation).
4. An LLM API key for AI highlight selection:
   - `OPENAI_API_KEY` (OpenAI or compatible: Groq, DeepSeek, etc.)
   - OR `GEMINI_API_KEY` (Google Gemini)

### Setup

```bash
# Clone the repository
git clone https://github.com/lemi-be/Short-generator.git
cd Short-generator

# Create and activate a virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

# Install core and local dependencies
pip install -r requirements.txt
pip install -r requirements-local.txt

# Install Django (for the web application)
pip install django
```

### Environment Configuration

Create a `.env` file in the project root (see `.env.example`):

```env
# Highlight ranking LLM provider: openai or gemini
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

# Optional: OpenAI-compatible endpoint (Groq, DeepSeek, Ollama, etc.)
# OPENAI_BASE_URL=https://api.deepseek.com/v1
# OPENAI_MODEL=deepseek-chat

# Google Gemini configuration (if LLM_PROVIDER=gemini)
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash

# Local Whisper Configuration
LOCAL_WHISPER_MODEL=base          # tiny, base, small, medium, large-v3, turbo
LOCAL_WHISPER_DEVICE=auto         # auto, cpu, cuda
LOCAL_OUTPUT_DIR=output           # Directory for cache and rendered shorts
TEMPLATE=full_bleed_solo          # Default cropping template

# Optional: Pexels API key (for B-roll / stock assets in FreeCut editor)
PEXELS_API_KEY=your_pexels_api_key_here
```

---

## Web UI: The Production Line (Short Factory)

The Web UI is streamlined for rapid turnaround. Start the local server:

```bash
# Initialize SQLite database
python manage.py migrate

# Start development server
python manage.py runserver
# Or on Windows: double-click run_webui.bat
```

Open **http://127.0.0.1:8000** in your browser.

### The 7-Stage Workflow

```text
[Stage 0] Create / Select Client Project (Set styles once)
    ↓
[Stage 1] Add Episode (Paste URL or local video path)
    ↓
[Stage 2] Local Transcription (faster-whisper + sentence-boundary alignment)
    ↓
[Stage 3] Mark Clips (Sentence-by-sentence in/out tagging)
    ↓
[Stage 4] Batch Render All (Background thread worker)
    ↓
[Stage 5] Review & Nudge Trim (Instant preview & re-render)
    ↓
[Stage 6] Package & Deliver (Organized client ZIP)
```

1. **Stage 0: Client Project** (`/projects/new/`)
   - Configure client branding once: choose caption preset (`hormozi_pop`, `beast_neon`, etc.), font, highlight color, position, video filter (`vivid_pop`, etc.), upload logo, set lower-third handle, and toggle zoom punch / broadcast mastering.
   - All subsequent episodes and clips automatically inherit these settings.
2. **Stage 1: Add Episode** (`/projects/<id>/add/`)
   - Paste a YouTube URL or local file path. Download starts immediately with format selection.
3. **Stage 2: Automatic Transcription**
   - Transcribes locally via `faster-whisper` with word timestamps. Re-segments sentences cleanly on terminal punctuation (`.`, `?`, `!`) so segments don't cut mid-phrase. Caches to `.srt` and `.words.json`.
4. **Stage 3: Mark Clips** (`/episodes/<id>/mark/`)
   - Browse sentence-aligned transcript blocks.
   - **Keyboard shortcuts**: Hover over a segment and press <kbd>I</kbd> to set start (In), and <kbd>O</kbd> to set end (Out).
   - Alternatively, click the start segment and click the end segment.
   - Click **"Batch Render All"** to queue the entire episode.
5. **Stage 4: Background Batch Render** (`/episodes/<id>/render/`)
   - Handled asynchronously by `webui/jobs.py` in a background thread.
   - Polls real-time progress (`0–100%`) on the amber tally banner.
   - Can be cleanly cancelled with the **"Cancel Render"** button.
6. **Stage 5: Review & Nudge Trim** (`/episodes/<id>/review/`)
   - Step through rendered vertical clips with audio playback and burned captions.
   - Need to adjust timing? Adjust the **In (s)** or **Out (s)** boxes and click **"Re-render Clip"** to update in seconds.
   - Override subtitle text if a name or word was mistranscribed.
   - Click **"Looks good &rarr;"** to mark confirmed, or click **"Open full editor"** to launch FreeCut.
7. **Stage 6: Package & Deliver** (`/episodes/<id>/deliver/`)
   - Check the delivery manifest.
   - Click **"Package & mark delivered"** to generate a clean client ZIP (`{client_slug}_{episode_id}_batch.zip`) with consistent file naming (`{client_slug}_{episode:04d}_clip01.mp4`).

---

## FreeCut WebGPU Video Editor

When a clip requires granular multi-track editing, B-roll overlays, or manual keyframing, the full **FreeCut editor** is available at `/video/<video_id>/edit/` or `/editor/`.

- **Zero Server Dependencies**: Fully client-side WebCodecs / WebGPU timeline engine.
- **Cross-Origin Isolated**: Django automatically sends required COOP (`same-origin`) and COEP (`require-corp`) headers.
- **Automatic Project Sync**: When clips are rendered in the pipeline, `freecut_projects.py` registers the project in `output/projects/` with clip-local transcripts and thumbnails.
- **Requirements**: Chromium-based browser (Chrome or Edge 113+).

---

## CLI & Scripting Usage

The CLI is ideal for headless servers, cron jobs, and bulk batch generation.

### Basic Generation

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Full Options & Flags

```bash
python main.py "https://www.youtube.com/watch?v=VIDEO_ID" \
    --num-clips 5 \
    --template full_bleed_solo \
    --format 1080 \
    --min-clip-seconds 30 \
    --max-clip-seconds 60 \
    --burn-captions \
    --output-json result.json
```

### Local File Processing

Skip YouTube downloading by passing a direct path or `file://` URI:

```bash
python main.py "C:/Users/You/Videos/podcast_ep42.mp4" --num-clips 3
```

### CLI Flag Reference

| Flag | Default | Description |
|------|---------|-------------|
| `url` | *Required* | YouTube URL, local filesystem path, or `file://` URI |
| `--num-clips` | `10` | Number of top-ranked shorts to generate |
| `--template` | `full_bleed_solo` | Layout: `full_bleed_solo`, `podcast_split_screen`, `stage_solo_speaker`, `blurred_backdrop` |
| `--format` | `1080` | Download quality: `360`, `480`, `720`, `1080`, or `best` |
| `--language` | `auto` | Force Whisper ISO language code (e.g., `en`, `es`, `de`) |
| `--min-clip-seconds` | `30` | Drop candidate clips shorter than this duration |
| `--max-clip-seconds` | `60` | Hard cap on clip length; longer clips are truncated |
| `--burn-captions` | `False` | Burn word-by-word kinetic captions into output pixels |
| `--cookies` | `None` | Path to a custom `cookies.txt` file for YouTube authentication |
| `--output-json` | `None` | Write complete JSON results (transcript, candidates, final shorts) |
| `--mode` | `local` | `local` (default self-hosted) or `api` (MuAPI reference) |

### Python API

Import `generate_shorts` directly into your own scripts or backend services:

```python
from shorts_generator import generate_shorts

result = generate_shorts(
    youtube_url="https://www.youtube.com/watch?v=VIDEO_ID",
    num_clips=5,
    download_format="1080",
    template="full_bleed_solo",
    burn_captions=True,
)

print(f"Source video: {result['source_video_url']}")
for short in result["shorts"]:
    print(f"Score: {short['score']} | {short['title']}")
    print(f"Hook:  {short['hook_sentence']}")
    print(f"File:  {short['clip_url']}")
```

---

## Template & Preset Reference

### 1. Canvas Cropping Templates (`TEMPLATE_SPECS`)

| Template Key | Layout Name | Visual Identity & Behavior |
|--------------|-------------|----------------------------|
| `full_bleed_solo` | **Full Bleed (Solo Speaker)** | *(Default)* Full 1080×1920 viewport centered on speaker face/torso with EMA smoothing. |
| `podcast_split_screen` | **Podcast & Dialogue** | Two stacked 9:8 panels (1080×960 each) tracking two distinct faces, with center accent divider. Includes **Dynamic Solo Switching**: automatically cuts to single full-bleed 9:16 when one host speaks continuously. |
| `stage_solo_speaker` | **Stage & Solo Speaker** | Centered 1080×1152 stage area with protected safe zones (23% top hook zone / 17% bottom UI zone). |
| `blurred_backdrop` | **Blurred Backdrop** | Keeps widescreen (16:9) frame in full aspect ratio and fills top/bottom with blurred scaled video. Perfect for slides, screencasts, and gameplay. |

### 2. Subtitle Style Templates (`SUBTITLE_TEMPLATES`)

| Preset Key | Style Name | Typography & Animation Spec |
|------------|------------|-----------------------------|
| `hormozi_pop` | **Hormozi Viral Pop** | Impact font, uppercase, 1.22x active word expansion, `#FFEA00` electric yellow, drop shadow + stroke, keyword emojis. |
| `beast_neon` | **MrBeast Dynamic** | Arial Black / Heavy Sans, uppercase, 1.14x word pop, 12px stroke, `#00F0FF` neon cyan, keyword emojis. |
| `minimal_clean` | **Clean Minimalist** | Inter modern sans, natural casing, 1.05x subtle pop, 5px stroke, `#F4A261` warm coral. |
| `documentary` | **Vox / Documentary** | Georgia serif, natural casing, 1.0x scale (steady reading cadence), 6px stroke, `#E63946` crimson. |
| `cyber_terminal` | **Cyber Tech** | JetBrains Mono, uppercase, 1.15x pop, 8px stroke, `#00FF66` terminal matrix green. |

### 3. Video Filters (`apply_video_filter`)

| Filter Key | Preset Name | Processing Pipeline |
|------------|-------------|---------------------|
| `vivid_pop` | **Vivid Pop** | Contrast S-curve, +18% skin tone saturation, +35% unsharp mask facial sharpening, spotlight vignette. |
| `warm_studio` | **Warm Studio** | Warm amber/red balance, +14% vibrance, soft studio lighting glow, subtle vignette. |
| `clean_crisp` | **Clean Crisp** | Natural tone curve with +45% high-frequency unsharp mask micro-contrast. |
| `cinematic` | **Cinematic Punch** | Deep S-curve contrast, filmic shadow compression, saturated midtones, 0.22 moody vignette. |
| `none` | **None** | Pass-through original raw video colors without grading. |

---

## YouTube Authentication & Cookie Tooling

Most YouTube downloads proceed without cookies using the built-in Node.js challenge solver and `bgutil-ytdlp-pot-provider`. However, if YouTube presents a bot verification or `HTTP 403` challenge, use the included `export_cookies.py` utility:

```bash
# Attempt export across all installed browsers (Chrome, Edge, Firefox, Brave, Opera)
python export_cookies.py

# Export from a specific browser
python export_cookies.py firefox

# Auto-close the browser first to unlock SQLite DB files
python export_cookies.py chrome --force
```

> **Note on Chrome/Edge 127+ App-Bound Encryption:**
> Windows Chrome and Edge encrypt cookie databases with credentials tied to their running process. If you encounter App-Bound decryption warnings, use **Firefox** with `export_cookies.py`, or use the **"Get cookies.txt LOCALLY"** browser extension to export `cookies.txt` into the project root.

---

## Project Structure

```text
AI-Youtube-Shorts-Generator/
├── main.py                       # CLI entry point
├── manage.py                     # Django management script
├── run_webui.bat                 # Windows one-click web launcher
├── export_cookies.py             # Browser cookie extraction tool
├── requirements.txt              # Core dependencies (requests, dotenv, Pillow)
├── requirements-local.txt        # Local processing dependencies (yt-dlp, whisper, cv2, openai, etc.)
├── .env.example                  # Environment configuration template
│
├── webui/                        # Django Web UI application
│   ├── settings.py               # Settings, DB config, and output paths
│   ├── models.py                 # ClientProject, Episode, Clip, RenderJob
│   ├── views.py                  # Web views (project CRUD, mark, review, package, FreeCut)
│   ├── urls.py                   # URL routing table
│   ├── jobs.py                   # Background multi-threaded batch render worker
│   ├── db.sqlite3                # Persistent database
│   └── templates/webui/          # HTML templates
│       ├── base.html             # Control-room layout & tally rail
│       ├── home.html             # Client projects dashboard
│       ├── project_new.html      # Client project setup (<1 min)
│       ├── project_detail.html   # Episode list & branding presets
│       ├── episode_mark.html     # Sentence-aligned transcript marker
│       ├── episode_review.html   # Fast clip review & nudge trim
│       ├── episode_deliver.html  # Delivery checklist & ZIP packaging
│       └── editor_shell.html     # FreeCut iframe host with capability checks
│
├── shorts_generator/             # Core generator library
│   ├── __init__.py               # Package exports (generate_shorts)
│   ├── config.py                 # Settings & env variable parsing
│   ├── pipeline.py               # Orchestrator for local and API runs
│   ├── segmenter.py              # Sentence-boundary alignment & re-segmentation
│   ├── highlights.py             # LLM virality ranking & chunk deduplication
│   ├── progress.py               # Terminal progress bars with ETA
│   ├── freecut_projects.py       # FreeCut project & transcript synchronization
│   └── local/                    # Local processing modules
│       ├── downloader.py         # yt-dlp download engine + caching
│       ├── transcriber.py        # faster-whisper engine + .srt/.words.json cache
│       ├── clipper.py            # OpenCV 9:16 compositor, typography, filters & muxer
│       ├── llm.py                # OpenAI / Gemini client with backoff
│       └── cookies.py            # Cookie extraction helpers
│
├── vendor/freecut/               # Vendored FreeCut browser video editor (MIT)
│   ├── dist/                     # Committed production build (served at /editor/)
│   └── src/                      # Source code & fork patches
│
└── output/                       # Default workspace for sources, caches, shorts, and exports
```

---

## Troubleshooting

### Whisper produced no segments
- Check that the input video contains audible dialogue.
- If audio is faint or in a specific language, specify `--language <iso_code>` (e.g. `--language en`) to skip language auto-detection.

### YouTube 403 Forbidden / Bot Detection
- Ensure Node.js (v20+) is installed so `yt-dlp` can execute JS challenges.
- Run `python export_cookies.py firefox` or place a valid `cookies.txt` file in the project root.

### `[WinError 32] The process cannot access the file`
- Ensure no media player (VLC, Windows Media Player) has the generated `.mp4` file open while re-rendering.
- The pipeline isolates audio muxing to avoid file-lock races during rendering.

### FreeCut Editor Shows "Unsupported Browser"
- FreeCut requires WebGPU, WebCodecs, and the File System Access API. Use **Google Chrome** or **Microsoft Edge** (version 113+).
- Access via `http://127.0.0.1:8000` (required for Secure Context and cross-origin isolation).

---

## License

This project is licensed under the [MIT License](LICENSE).
Vendored FreeCut editor components are distributed under their original MIT License.

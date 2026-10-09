# Short Factory — AI YouTube Shorts Generator & Production Line

Turn long-form videos into viral, client-ready vertical (9:16) shorts. Point it at any YouTube URL or local video file, and it downloads the source, transcribes it locally with Whisper, detects sentence boundaries, ranks highlight moments with a virality framework, and renders 1080×1920 MP4s with motion-smoothed face tracking, dynamic kinetic typography, broadcast vocal mastering, and cinematic color grading.

Equipped with both a **high-throughput Web UI (Short Factory)** built for fast client batch delivery (under ~10–15 min operator turnaround) and a **fully scriptable CLI & Python pipeline**.

---

## The 7-Stage Production Workflow

Short Factory is designed around a fast, repeatable B2B client production line:

```text
┌────────────────────────┐      ┌────────────────────────┐      ┌────────────────────────┐
│ 1. Client Project      │ ───► │ 2. Add Podcast         │ ───► │ 3. Download & Transcribe│
│ Name, branding, style  │      │ YouTube URL / local    │      │ yt-dlp + faster-whisper │
└────────────────────────┘      └────────────────────────┘      └───────────┬────────────┘
                                                                            │
┌────────────────────────┐      ┌────────────────────────┐      ┌───────────▼────────────┐
│ 6. Review & Approve    │ ◄─── │ 5. Background Render   │ ◄─── │ 4. Mark 5–8 Clips      │
│ In-browser player/trim │      │ Reframing + subtitles  │      │ Sentence-aligned marker│
└──────────┬─────────────┘      └────────────────────────┘      └────────────────────────┘
           │
┌──────────▼─────────────┐
│ 7. Package & Deliver   │
│ 1-Click ZIP bundle     │
└────────────────────────┘
```

1. **Create a client project** — Set the client's caption style, active word highlight color, font, lower-third branding, video filter, and audio mastering once. All settings are inherited automatically by every episode and clip.
2. **Add a podcast** — Provide a YouTube link or local video file path.
3. **Download and transcribe** — Local `yt-dlp` retrieves the video and `faster-whisper` extracts word-level timestamps with sentence-boundary alignment, cached to disk (`.srt` and `.words.json`).
4. **Select 5–8 clips** — Highlight key moments in the interactive transcript marker (hotkey-friendly: `I` mark-in, `O` mark-out, `Space` play/pause) or use AI highlight ranking.
5. **Render the batch** — Background render job reframes the video to 9:16, centers speakers with two-pass face tracking, applies color grading, burns kinetic subtitles, and master vocal audio.
6. **Review and approve** — Watch the rendered shorts in the review player, fine-tune cut points with instant re-rendering, and mark clips as approved.
7. **Package and deliver** — 1-click downloads a clean ZIP package (`{client}_{episode}_shorts.zip`) ready to deliver to the client.

---

## Core Capabilities

### 1. Control-Room Tally Light Status
Instant visual state cues across projects, episodes, and clips:
- 🔴 **Red**: Awaiting operator action (unmarked transcript or unconfirmed clip).
- 🟡 **Amber**: Automated background task in progress (downloading, transcribing, batch rendering).
- 🟢 **Green**: Ready, confirmed, or packaged for delivery.

### 2. Advanced 9:16 Compositing Engine
4 specialized vertical canvas layouts:
- `full_bleed_solo` *(Default)*: Full-height vertical crop centered on the speaker.
- `podcast_split_screen`: Stacked 50/50 dual view (two 9:8 panels) with center seam divider + **Dynamic Solo Switching** (cuts automatically to full-bleed when one speaker dominates).
- `stage_solo_speaker`: 1080×1152 active stage framed with dedicated top/bottom safe zones (23% top / 17% bottom).
- `blurred_backdrop`: Centered widescreen video with gaussian blurred fill (ideal for presentations, gaming, widescreen charts, or code walkthroughs).

### 3. Kinetic Word-by-Word Subtitle Engine
Pillow-rendered TrueType typography with outer stroke, drop shadow, and active spoken word expansion:
- `hormozi_pop`: Impact bold, 1.22x active word expansion, `#FFEA00` electric yellow, keyword emojis.
- `beast_neon`: Heavy sans, 1.14x pop, 12px heavy stroke, `#00F0FF` neon cyan, keyword emojis.
- `minimal_clean`: Inter sans, 1.05x subtle pop, `#F4A261` warm coral, natural casing.
- `documentary`: Georgia serif, editorial crimson `#E63946`, flat reading cadence.
- `cyber_terminal`: JetBrains Mono, 1.15x pop, uppercase terminal green `#00FF66`.

### 4. Contextual Keyword Emojis
Keywords like *money*, *fire*, *secret*, *mistake*, *win*, *brain*, *danger* dynamically display contextual visual emojis next to the spoken word.

### 5. Broadcast Vocal Mastering Chain
Integrated FFmpeg audio mastering:
- 80 Hz highpass filter (removes mic plosives, room rumble, and desk thumps).
- 3 kHz presence EQ (+2 dB, Q=1.0) (maximizes speech intelligibility on mobile phone speakers).
- Native `loudnorm` normalization targeting the industry-standard **-14 LUFS** (-1.5 dBTP true peak).
- High-fidelity 192k AAC 48 kHz encoding.

### 6. Speaker Visual Filters
Real-time OpenCV LUT color grading:
- `vivid_pop` *(Default)*: S-curve contrast, +18% skin vibrance, +35% unsharp mask facial sharpening, spotlight vignette.
- `warm_studio`: Golden amber/red tone boost, +14% saturation, soft glow.
- `clean_crisp`: High clarity, +45% micro-contrast unsharp mask.
- `cinematic`: Moody filmic shadows, deep contrast, rich saturation, 0.22 vignette.
- `none`: Clean source pass-through.

### 7. Sentence-Boundary Alignment
Re-segments raw Whisper transcripts so in/out cut points fall strictly on natural sentence punctuation (`.`, `?`, `!`), eliminating awkward mid-sentence audio cuts.

### 8. Two-Pass Motion Smoothing
Pass 1 pre-scans at low FPS, detects faces, computes union bounding boxes, and filters coordinates with median filtering + Exponential Moving Average (EMA) + smoothstep interpolation. Pass 2 renders from the pre-computed trajectory with zero micro-jitter.

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
       │  local/:               │       │   - Background Worker  │
       │   - downloader (yt-dlp)│       │     (webui/jobs.py)    │
       │   - transcriber        │       │   - Review & Nudge     │
       │   - clipper (OpenCV)   │       │   - Delivery Packager  │
       │   - llm (OpenAI/Gemini)│       └────────────────────────┘
       └────────────────────────┘
```

---

## Installation & Setup

### Prerequisites

1. **Python 3.10+** (Python 3.11 or 3.12 recommended)
2. **ffmpeg** and **ffprobe** installed and available on your system `PATH`.
3. **Node.js (v20+)** (optional, recommended for `yt-dlp` JavaScript challenge execution).
4. An LLM API key for AI highlight selection:
   - `OPENAI_API_KEY` (OpenAI or compatible: Groq, DeepSeek, etc.)
   - OR `GEMINI_API_KEY` (Google Gemini)
   - OR local **Ollama** running at `http://localhost:11434`.

### Installation Steps

```bash
# 1. Clone the repository
git clone https://github.com/lemi-be/Short-generator.git
cd Short-generator

# 2. Create and activate a virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Install pipeline dependencies (Whisper, yt-dlp, OpenCV, LLM SDKs)
pip install -r requirements-local.txt

# 5. Initialize the database
python manage.py migrate
```

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in your keys:

```ini
# LLM Provider for Highlight Detection: "openai" or "gemini"
LLM_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

# Optional: Gemini configuration
# GEMINI_API_KEY=your_gemini_api_key_here
# GEMINI_MODEL=gemini-2.0-flash

# Optional: DeepSeek or custom OpenAI-compatible endpoint
# OPENAI_BASE_URL=https://api.deepseek.com/v1

# Local Whisper settings
LOCAL_WHISPER_MODEL=base          # tiny, base, small, medium, large-v3
LOCAL_WHISPER_DEVICE=auto         # auto, cpu, cuda
LOCAL_OUTPUT_DIR=output

# Optional: Pexels API key for B-roll panel
PEXELS_API_KEY=your_pexels_api_key_here
```

---

## Running the Application

### Option 1: Web UI (Recommended)

On Windows, double-click `run_webui.bat`, or run:

```bash
python manage.py runserver
```

Open your browser to: **http://127.0.0.1:8000/**

1. Click **+ New Client Project** to define the visual style and branding.
2. Click **+ Add Episode** and paste a YouTube URL or local file path.
3. Click **Download** then **Transcribe**.
4. Click **Mark clips** to pick in/out points from the transcript.
5. Click **Render all marked →**.
6. Check the clips in **Review**, confirm approvals, and click **Package for delivery**.

### Option 2: CLI Automation

Run the standalone pipeline directly from the command line:

```bash
python main.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" \
  --num-clips 5 \
  --format 1080 \
  --template full_bleed_solo \
  --burn-captions \
  --output-json output/results.json
```

#### CLI Arguments:

| Argument | Description | Default |
|---|---|---|
| `url` | YouTube URL, `file://` URL, or local file path | *(required)* |
| `--num-clips` | Number of shorts to produce | `10` |
| `--format` | Download resolution: `360`, `480`, `720`, `1080`, `best` | `1080` |
| `--language` | Force Whisper ISO language code (e.g., `en`, `es`, `fr`) | `auto` |
| `--min-clip-seconds` | Minimum clip duration (seconds) | `30` |
| `--max-clip-seconds` | Maximum clip duration (seconds) | `60` |
| `--template` | `full_bleed_solo`, `podcast_split_screen`, `stage_solo_speaker`, `blurred_backdrop` | `full_bleed_solo` |
| `--burn-captions` | Burn word-by-word subtitles into rendered pixels | `False` |
| `--cookies` | Path to a `cookies.txt` file for YouTube authentication | `None` |
| `--output-json` | Path to write the structured result JSON | `None` |

---

## Testing

Run the automated test suite locally:

```bash
# Run Django system checks
python manage.py check

# Run the 23-test unit suite
python manage.py test webui
```

---

## License

This project is licensed under the MIT License.

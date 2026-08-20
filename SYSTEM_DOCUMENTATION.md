# AI YouTube Shorts Generator — Complete System Documentation

> **Version:** Current working state of the repository
> **Scope:** Covers the Short Generator pipeline, the Django Web UI, and the vendored FreeCut browser editor — every feature, nothing left out.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Short Generator — Complete Feature Inventory](#3-short-generator--complete-feature-inventory)
4. [Web UI (Django) — Complete Feature Inventory](#4-web-ui-django--complete-feature-inventory)
5. [FreeCut Editor — Complete Feature Inventory](#5-freecut-editor--complete-feature-inventory)
6. [Integration: How Shorts Flow Into the Editor](#6-integration-how-shorts-flow-into-the-editor)
7. [Configuration Reference](#7-configuration-reference)
8. [Project Structure](#8-project-structure)

---

## 1. System Overview

This project is a **two-part system** that turns long-form videos into viral-ready vertical (9:16) shorts:

1. **The Short Generator** — a Python pipeline (CLI + library) that downloads a source video, transcribes it, ranks the most shareable moments through a virality-aware LLM framework, and renders each highlight as a 1080×1920 vertical mp4 with face tracking, word-by-word captions, and a choice of cropping templates.
2. **The Web UI + FreeCut Editor** — a Django web application that wraps the pipeline in a browser interface and embeds **FreeCut**, a fully client-side, browser-based multi-track video editor (WebGPU/WebCodecs), for fine-cutting, reframing, captions, text, music, and export.

**Key design decisions:**

- **Local-first.** Everything runs on the user's machine. The only remote call in the default (`local`) mode is the highlight-ranking LLM (OpenAI or Gemini). An older `api` mode (MuAPI, pay-per-call) is kept for reference.
- **The FreeCut editor is the only editor.** The legacy ffmpeg-based trimmer has been removed. FreeCut is vendored (a fully-owned fork, no remote, no auto-update) and committed as a production build so the runtime needs **no Node.js and no network**.
- **Captions are not double-burned.** By default, generated shorts are rendered clean (no burned captions); captions are added as layers in the FreeCut editor and baked in at export time.
- **One workspace.** The FreeCut workspace is the app's `output/` directory, so sources, transcripts, audio, logos, stock clips, generated shorts, and editor exports all live in one place.

---

## 2. Architecture

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                            ENTRY POINTS                                    │
│                                                                            │
│   main.py (CLI)          manage.py / run_webui.bat (Django Web UI)         │
└──────────┬──────────────────────────────┬──────────────────────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐      ┌─────────────────────────────────────────────┐
│  shorts_generator/   │      │  webui/ (Django)                            │
│  (pipeline library)  │      │  - home / download / transcribe             │
│                      │      │  - clip editor / auto-generate              │
│  local/ (default):   │      │  - editor shell (embeds FreeCut)            │
│   downloader (yt-dlp)│      │  - serves /editor/ + /output/ (byte-range)  │
│   transcriber (whisper)     │  - freecut_projects.py (auto-sync)          │
│   llm (OpenAI/Gemini)│      └───────────────┬─────────────────────────────┘
│   clipper (ffmpeg+cv2)                      │
│   cookies (auth)     │                      ▼
│  api/ (MuAPI, ref)   │      ┌─────────────────────────────────────────────┐
└──────────────────────┘      │  vendor/freecut/ (browser NLE)              │
                              │  - served at /editor/ with COOP/COEP        │
                              │  - workspace = output/ (File System Access) │
                              └─────────────────────────────────────────────┘
```

### Data flow (typical end-to-end)

1. **Download** → `output/source_<id>.mp4` (+ `.title` sidecar)
2. **Transcribe** → `output/source_<id>.srt` (+ `.words.json` word timestamps)
3. **Highlight ranking** → LLM returns scored candidates (0–100), clamped 30–60s, deduped
4. **Clip creation** → `Clip` rows in SQLite (`webui/db.sqlite3`)
5. **Render** → `output/short_<id>_c<clip_id>.mp4` (+ `.meta.json` source window)
6. **FreeCut sync** → `freecut_projects.py` creates/updates a project in the workspace, registers the shorts as media, writes clip-local transcripts
7. **Edit & Export** → FreeCut writes exports to `output/projects/<id>/exports/`, which appear on the home page

---

## 3. Short Generator — Complete Feature Inventory

### 3.1 Pipeline orchestrator (`shorts_generator/pipeline.py`)

`generate_shorts(...)` is the main entry point, with two modes:

| Mode | Description | Status |
|------|-------------|--------|
| `local` (default) | `yt-dlp` + `faster-whisper` + OpenAI/Gemini + `ffmpeg`/OpenCV. Self-hosted. | Active |
| `api` | MuAPI does download / transcribe / LLM / autocrop. Pay-per-call, no local deps. | Kept for reference |

**Parameters:** `youtube_url`, `num_clips` (default 10), `download_format` (360/480/720/1080), `language`, `mode`, `min_clip_seconds` (default 30), `max_clip_seconds` (default 60), `template`, `burn_captions` (default False).

**Returned result:** `{mode, source_video_url, transcript, highlights (all candidates), shorts (top N with clip_url), template}`.

### 3.2 Download (`shorts_generator/local/downloader.py`)

- **Input flexibility:** accepts a YouTube URL, a `file://` URL, or a direct local filesystem path (skips YouTube entirely for local files).
- **Format selection:** maps `360/480/720/1080` shorthand to a `yt-dlp` format selector (`bestvideo[height<=N][ext=mp4]+bestaudio[ext=m4a]/...`).
- **YouTube ID extraction:** handles `youtu.be`, `/watch?v=`, `/shorts/`, `/embed/`, `/live/` URL forms.
- **Caching:** reuses an existing download for the same video ID (`.mp4`/`.mkv`/`.webm`).
- **Title sidecar:** writes the YouTube title to `source_<id>.title` so later stages can name a FreeCut project without another network call.
- **Auth / bot-detection fallback chain:**
  1. Try a normal download.
  2. If an auth/bot error is detected, try a **manual `cookies.txt`** in the project root (friendliest option).
  3. Otherwise try **browser cookies** (Chrome, Edge, Firefox, Brave, Opera) via `yt-dlp --cookies-from-browser`.
  4. If all fail, raise a helpful error explaining how to export cookies.
- **Robustness:** 10 retries for downloads/fragments/file access, `noplaylist`, progress hooks, and a clear error message distinguishing auth problems from network/format problems.

### 3.3 Cookie extraction (`shorts_generator/local/cookies.py`)

- `find_manual_cookies()` — looks for `cookies.txt` in the CWD or project root.
- `try_browser_cookies(url)` — iterates browsers, extracts cookies to a temp file, cleans up on failure, and warns about locked/encrypted cookie DBs (App-Bound encryption).
- Invokes `yt-dlp` via `python -m yt_dlp` (avoids a broken uv-generated `yt-dlp.exe` trampoline), falling back to a PATH `yt-dlp`.

### 3.4 Transcription (`shorts_generator/local/transcriber.py`)

- **Engine:** `faster-whisper` (CPU or CUDA), model configurable (`tiny`/`base`/`small`/`medium`/`large-v3`/`turbo`).
- **Word-level timestamps:** enabled (`word_timestamps=True`) so captions can be highlighted in sync with audio.
- **Language:** auto-detect or forced via ISO-639-1 code.
- **Device resolution:** `auto` probes CUDA (with a real tensor test to catch missing cuBLAS/cuDNN), falls back to CPU; compute type `float16` on CUDA, `int8` on CPU.
- **VAD (Voice Activity Detection):** optional, off by default (too aggressive on mixed speech/music). Configurable threshold / min speech / min silence / speech pad.
- **Caching:** writes `.srt` + a `.words.json` sidecar. Re-runs reuse the cache if it's newer than the source and has word timestamps; stale/empty/invalid caches are deleted and re-transcribed.
- **Output shape:** `{duration, segments: [{start, end, text, words: [{start, end, word}]}]}`.

### 3.5 Highlight ranking (`shorts_generator/highlights.py`)

- **Content-type detection:** an LLM classifies the video (`podcast`, `interview`, `tutorial`, `lecture`, `commentary`, `debate`, `vlog`, `other`) and density (`low`/`medium`/`high`) so the prompt is tuned per content style.
- **Virality framework** (`VIRALITY_CRITERIA`), ranked by impact:
  1. **Hook moments** — statements that create immediate curiosity
  2. **Emotional peaks** — genuine surprise, laughter, anger, vulnerability, excitement
  3. **Opinion bombs** — strong, polarizing, counter-intuitive statements
  4. **Revelation moments** — surprising facts, stats, or confessions
  5. **Conflict/tension** — disagreement, pushback, or a problem confronted head-on
  6. **Quotable one-liners** — standalone quote-card sentences
  7. **Story peaks** — climax or twist of an anecdote
  8. **Practical value** — concrete tips/hacks/insights
- **System prompt rules:** hard 30–60s duration cap, every clip must open with a strong hook (within first 3s), never cut mid-sentence, clips must not overlap, score 0–100 on viral potential, each highlight carries a `hook_sentence` and a one-sentence `virality_reason`.
- **Long-video chunking:** videos > 30 min (`LONG_VIDEO_THRESHOLD = 1800`) are split into 10-min chunks (`CHUNK_SIZE_SECONDS = 600`) with 60s overlap (`CHUNK_OVERLAP_SECONDS`). Chunk timestamps are offset back to source time. Failed chunks are skipped without failing the whole run.
- **Retry logic:** up to 3 attempts (`MAX_HIGHLIGHT_API_ATTEMPTS`) with a corrective prompt on invalid JSON; 5-min LLM call timeout.
- **Sanitization:** clamps every clip to `[min, max]` seconds (truncates from the right to preserve the hook), drops clips shorter than the minimum, clamps scores to 0–100, and coerces types.
- **Dedupe:** overlapping candidates are collapsed by score — a highlight is dropped if it overlaps >50% with a higher-scoring one already kept.
- **Pluggable LLM:** `llm_fn` argument swaps the backend (local OpenAI/Gemini vs MuAPI `gpt-5-mini`).

### 3.6 Local LLM backend (`shorts_generator/local/llm.py`)

- **Two providers:** `LLM_PROVIDER=openai` (OpenAI Chat Completions, works with Groq/DeepSeek via `OPENAI_BASE_URL`) or `LLM_PROVIDER=gemini` (Google GenAI, JSON response mode).
- **Retry/backoff:** up to 4 attempts with exponential backoff (2s, 4s, 8s, 16s) on transient errors (429, 503, 500, 502, 504, rate limits, timeouts, connection resets).
- **Gemini free-tier pacing:** enforces a minimum 12s interval between calls (5 req/min free tier).

### 3.7 Clipping & rendering (`shorts_generator/local/clipper.py`)

**Output is always 9:16 (1080×1920).** Three stages per highlight:

1. **Cut** — ffmpeg cuts the source to `[start, end]` (video only; audio is read from the original source later to avoid a Windows file-lock race).
2. **Reframe** — OpenCV reads the cut, applies the template's composition strategy, writes a silent 9:16 video with optional text overlays/widgets.
3. **Mux** — ffmpeg muxes the silent reframed video with audio from the original source (input seek), re-encoding to H.264 (`yuv420p`, `+faststart`) + AAC 128k.

**Canvas spec (1080×1920):**
- `TOP_SAFE_H` = 441px (23%) — hook/UI safe zone
- `STAGE_H` = 1152px (60%) — talking stage
- `BOTTOM_SAFE_H` = 327px (17%) — name tag / TikTok UI safe zone
- Caption band at y 1180–1500, captions never exceed 80% width, max 5 words per batch, accent color `#ff914d`

**Templates (`TEMPLATE_SPECS`):**

| Key | Label | Layout |
|-----|-------|--------|
| `stage_solo_speaker` | Stage & Solo Speaker | Video fills a 1080×1152 "stage"; hook title in the top safe zone; word-by-word captions in the lower band |
| `podcast_split_screen` | Podcast & Dialogue | Two stacked 9:8 panels (1080×960 each); each half tracks its own speaker's face |

**Two-pass face-tracking render (`_reframe_composed`):**
- **Pass 1 (pre-scan):** samples at low FPS, detects **all** faces, computes the union bounding box (keeps every face in frame), forward-fills missing detections, applies a median filter, EMA smoothing, and smoothstep interpolation to build a per-frame camera trajectory. Detects a **blur-fill fallback** condition when the scene is too wide for 9:16.
- **Pass 2 (render):** renders every frame from the pre-computed trajectory — no per-frame detection, zero jitter. Falls back to a **blurred-fill** (or solid) background when content doesn't fit 9:16.

**Decorations (`_decorate_frame`):**
- **Word-by-word captions** — a fixed batch of up to 5 words appears together, with the current word highlighted in the accent color as the speaker goes through it. Tight semi-transparent background box, wraps to 2 lines, never exceeds 80% width. Synced to real transcript word timestamps when available.
- **Hook title** — drawn in the top safe zone (stage layout).
- **Divider line** — 2px accent divider for the podcast split.
- **Color overlay** — optional RGBA tint.
- **Widgets** — e.g. a progress bar (bottom of canvas).

**Caption modes:**
- `burn_captions=False` (default): clean output; captions are added as layers in the FreeCut editor and baked at export time.
- `burn_captions=True`: word-by-word captions (from real transcript segments, offset to clip-local time) are burned into the frame pixels.

**Windows robustness:** OpenCV temp-copy to avoid locking the original, retry-based temp cleanup, `CREATE_NO_WINDOW` for ffmpeg, 10-min ffmpeg timeout.

### 3.8 Progress reporting (`shorts_generator/progress.py`)

- Dependency-free progress bars with **ETA**, elapsed time, and a spinner.
- Background ticker thread drives indeterminate stages (transcription, LLM ranking).
- Auto-detects UTF-8 vs ASCII terminals (falls back to ASCII to avoid encoding crashes).
- Disable via `PROGRESS_OFF=1`; force via `PROGRESS_FORCE`.

### 3.9 API mode (MuAPI, kept for reference)

- `downloader.py` — `/youtube-download` returns a hosted mp4 URL.
- `transcriber.py` — `/openai-whisper` with `verbose_json` (per-segment + per-word timestamps), robust payload extraction.
- `clipper.py` — `/autocrop` per highlight (9:16).
- `muapi.py` — thin submit → poll client with retries, SSL error hints, and a 10-min poll timeout.

### 3.10 CLI (`main.py`)

```
python main.py "URL" [--mode api|local] [--num-clips N] [--format 360|480|720|1080]
                   [--language CODE] [--min-clip-seconds N] [--max-clip-seconds N]
                   [--template stage_solo_speaker|podcast_split_screen]
                   [--burn-captions] [--output-json PATH]
```

- Reconfigures stdout/stderr to UTF-8 on Windows.
- Prints a summary (mode, template, source, highlights → kept top N) and per-clip details (score, times, title, hook, clip path).
- `--output-json` dumps the full result (transcript + all candidates + final clip paths) for downstream automation.

---

## 4. Web UI (Django) — Complete Feature Inventory

### 4.1 Home page (`/`)

- **Add a video:** paste a YouTube URL → **Download** (uses the local `yt-dlp` downloader at 720p).
- **Auto-generate (one-click pipeline):** paste a URL and configure:
  - **Clips** (1–20, default 10)
  - **Quality** (360p / 480p / 720p / 1080p)
  - **Language** (auto or ISO code)
  - **Min s / Max s** (clip length window, defaults 30–60)
  - **Template** (Stage & Solo Speaker / Podcast & Dialogue)
  - Runs download → transcribe → LLM highlight ranking → creates `Clip` rows → renders each to 9:16 (caption-free) → auto-creates a FreeCut project → redirects into the editor.
- **Source videos table:** lists each downloaded video with duration, a **pipeline status chain** (Downloaded → Transcribed → Clips → Generated), and actions (**Transcribe**, **Edit**, **Pick clips**).
- **Editor exports:** lists mp4s FreeCut wrote to `output/projects/<id>/exports/` (newest first), with download links.
- **Pipeline steps explainer** at the bottom.

### 4.2 Clip editor (`/video/<id>/`)

- **Pipeline breadcrumb** showing current stage.
- **Transcript browser:** scrollable SRT transcript with timestamps; **click a line to set the start time, click another to set the end**.
- **Add clip form:** manual `HH:MM:SS,mmm` start/end inputs with validation (end must be after start), or click transcript lines.
- **Selected clips list:** shows each clip's start → end and duration, with delete buttons.
- **Generate:** renders all selected clips at once with a chosen template. Writes `short_<id>_c<clip_id>.mp4` + a `.meta.json` sidecar (recording the source window so captions still map even if the Clip row is later deleted/recreated). Auto-creates/updates the FreeCut project.
- **Generated shorts list:** links to view each short (byte-range streaming) and an **Edit** button into the FreeCut editor.
- **Download SRT** button for the transcript.

### 4.3 Editor shell (`/video/<id>/edit/`)

- Full page embedding the FreeCut editor in an iframe, pointed at the project list.
- **Top bar:** back link, filename + duration, transcript download, view source, and a **capability check** (secure context, cross-origin isolation, WebGPU, WebCodecs, folder access, SharedArrayBuffer) with a clear "unsupported" message if any are missing.
- **Workspace hint:** tells the user to pick the `output/` folder on first launch (remembered via localStorage).
- **Exports panel:** live-fetches and lists editor exports with links.

### 4.4 FreeCut app server (`/editor/`)

- Serves the vendored FreeCut `dist/` build with **cross-origin-isolation headers** (COOP `same-origin`, COEP `require-corp`, CORP `same-origin`) so WebCodecs/SharedArrayBuffer work.
- Maps every URL under `/editor/` onto the committed `dist/` tree (assets, wasm, models, service worker), with **SPA fallback** for extensionless client-side routes.
- Path-traversal protection.
- Correct MIME types for html/js/css/json/svg/images/wasm/fonts/onnx/audio.

### 4.5 Output serving (`/output/<filename>`)

- Serves files from `output/` with **byte-range support** (206/416 handled correctly) for smooth video streaming.
- MIME mapping for mp4, webm, mp3, wav, m4a/aac, ogg, srt.

### 4.6 Transcript download (`/transcript/<id>/download/`)

- Downloads the `.srt` as an attachment.

### 4.7 Data model (`webui/models.py`)

- **`Clip`**: `video_id`, `start_time` (float), `end_time` (float), `created_at`. Ordered by creation.

### 4.8 Routes (`webui/urls.py`)

| Route | View | Purpose |
|-------|------|---------|
| `/` | `home` | Home page |
| `/download/` | `download` | Download a video |
| `/transcribe/<id>/` | `transcribe` | Transcribe a video |
| `/video/<id>/add/` | `add_clip` | Add a clip |
| `/video/<id>/delete/<clip_id>/` | `delete_clip` | Delete a clip |
| `/video/<id>/generate/` | `generate` | Generate shorts from clips |
| `/video/<id>/edit/` | `editor_shell` | Embed FreeCut editor |
| `/editor/` + `/editor/<path>` | `editor_app` | Serve FreeCut build |
| `/exports/` | `freecut_exports` | JSON list of editor exports |
| `/auto-generate/` | `auto_generate` | One-click pipeline |
| `/video/<id>/` | `clip_editor` | Clip editor |
| `/transcript/<id>/download/` | `download_transcript` | Download SRT |
| `/output/<filename>` | `serve_output` | Byte-range file serving |

---

## 5. FreeCut Editor — Complete Feature Inventory

FreeCut is a **browser-based, local-first, multi-track video editor** (vendored fork of `walterlow/freecut`, MIT, pinned commit `4d62e8082c5eb387a96275bcbd323d28f6e41a62`). It runs entirely in the browser via WebGPU, WebCodecs, Web Workers, OPFS, and the File System Access API. Projects and media stay local on disk as plain files.

**Browser requirement:** Chrome or Edge 113+ (WebGPU + WebCodecs + File System Access API). Brave may need `brave://flags/#file-system-access-api` enabled.

### 5.1 Timeline & Editing

- **Multi-track timeline** with video, audio, text, image, shape, mask, Lottie, and compound clip items.
- **Multiple timelines per project** as Sequences with tabs, unified with compound clips (open a compound clip as its own sequence).
- **Linked audio/video editing** with split, join, ripple, rolling, slip, slide, and rate-stretch tools.
- **Cut-centered transitions** with live resize, alignment, source-time anchoring, and preview overlays.
- **Track controls:** mute/visibility/lock, linked sync badges, track push/pull, and close-gap workflows.
- **Filmstrip thumbnails, stereo waveforms, snap guides, markers, timecode, and undo/redo.**
- **Source monitor** with mark in/out, patch destinations, insert edits, and overwrite edits.
- **Project templates**, auto-match canvas/FPS from first media, and configurable keyboard shortcuts.

### 5.2 Preview & Playback

- **Real-time preview** with transform, crop, corner-pin, mask, and group gizmos.
- **Frame-accurate playback** through a custom `Clock` and composition runtime.
- **Fast scrub overlays**, decoder prewarming, adaptive preview quality, and source warming.
- **Two-up and four-up edit panels** for ripple, rolling, slip, and slide operations.
- **GPU color scopes:** waveform, vectorscope, and histogram.
- **Separate project master bus** and monitor/device volume.

### 5.3 Audio

- **Clip volume, audio fades, track faders, master bus fader, and stereo LED meters.**
- **Per-clip pitch shift** in semitones/cents with SoundTouch preview playback.
- **Clip EQ and track EQ stages**, including a compact six-band floating EQ panel.
- Pitch, EQ, fades, volume, and transition audio paths preserved in preview and export.

### 5.4 Effects, Masks & Compositing (WebGPU-first)

- **Blur:** gaussian, box, motion, radial, zoom.
- **Color:** brightness, contrast, exposure, hue shift, saturation, vibrance, temperature/tint, levels, curves, color wheels, gradient map, LUT (`.cube`), grayscale, sepia, invert.
- **Distortion:** pixelate, RGB split, twirl, wave, bulge/pinch, kaleidoscope, mirror, fluted glass, ripple glass, glass mosaic, droste.
- **Stylize:** vignette, film grain, sharpen, posterize, glow, edge detect, scanlines, halftone, ASCII art, color glitch, block glitch, VHS, CRT, ink, pixel sort.
- **Keying:** chroma key with tolerance, softness, and spill suppression.
- **25 blend modes** (multiply, screen, overlay, soft light, difference, hue, saturation, color, luminosity, etc.).
- **Clip masks and pen paths** with keyframeable geometry transforms.
- **Color picker** with hex and alpha input, plus an in-app eyedropper with loupe.

### 5.5 Transitions

- Fade, wipe, slide, 3D flip, clock wipe, and iris transitions with directional variants.
- Dissolve, sparkles, glitch, light leak, pixelate, chromatic aberration, and radial blur.
- Adjustable duration, alignment, source anchoring, and Canvas 2D fallback for non-WebGPU paths.

### 5.6 Keyframe Animation

- **Bezier graph editor, dopesheet, split view, and multi-curve overlays.**
- **Easing presets** (linear, ease-in/out, cubic-bezier, spring) with a live-preview editor and saved custom presets.
- **Procedural motion modifiers** (drift, sway, breath, spin, shake) evaluated at render time, with one-click bake to keyframes.
- **Motion text:** per-character, per-word, and per-line text animation.
- **Auto-keyframe mode**, tangent mirroring, property accordions, and marquee selection.
- Animated transform, crop, mask, text, effect, and color properties.

### 5.7 Media & Import

- Import videos, audio, images, GIFs, SVGs, Lottie animations, and generated assets **without copying originals**.
- **Edit imported Lottie animations** (`.json` and `.lottie`): remap colors/themes, edit text, adjust value slots with live preview.
- **Apple ProRes decode** for import, preview, and thumbnails, including variants browsers can't natively decode.
- **Proxy generation, thumbnail extraction, waveform caching, and media relinking.**

### 5.8 Local AI & Analysis (on-device, nothing uploaded)

- **On-device transcription** with the Parakeet engine (Whisper fallback) and generated caption text items.
- **AI captioning** with local vision-language providers and configurable sample cadence.
- **Scene detection** with fast histogram or frame-accurate adaptive content analysis and optional model verification.
- **Scene Browser** for searching captioned media and reusing detected moments.
- **Local Kokoro text-to-speech** voiceovers.
- **Local MusicGen music generation** with presets, progress, and cancellation.
- **Local model cache controls** and unload controls in settings.

### 5.9 Projects & Storage

- **Workspace folder persistence** via the File System Access API.
- **Multi-workspace switcher** with known workspace management.
- Projects stored as **plain files on disk**, with legacy browser-storage migration.
- **Project soft-delete, restore, empty-trash, and permanent delete** flows.
- **Project ZIP bundle export/import** with Zod-validated schemas.
- **Auto-save, project thumbnails, workspace cache mirroring, and orphan cleanup.**

### 5.10 Export

- **In-browser rendering** through WebCodecs and worker-backed render paths.
- Export **any sequence**, not just the main timeline.
- **Video containers:** MP4, WebM, MOV, MKV.
- **Video codecs:** H.264, H.265, VP8, VP9, AV1 (where the browser provides an encoder).
- **Audio export formats:** MP3, AAC, WAV/PCM.
- **Subtitles:** off, burn-in, sidecar file, or embedded soft track (container-dependent).
- **Quality presets** from low to ultra, with runtime capability checks and fallbacks.

---

## 6. Integration: How Shorts Flow Into the Editor

`shorts_generator/freecut_projects.py` mirrors FreeCut's on-disk structures from Python so that every time a video is clipped into shorts, a project named after the YouTube title shows up in FreeCut with the shorts already registered.

### Workspace layout (the `output/` dir)

```text
output/
├── source_<id>.mp4 / .srt / .words.json / .title
├── short_<id>_c<clip_id>.mp4 / .meta.json
├── index.json                          # project list (version, updatedAt, projects)
├── projects/
│   └── <project_id>/
│       ├── project.json                # id, name, metadata (1080x1920@30), schemaVersion 15, sourceVideoId
│       ├── media-links.json            # mediaIds linked to this project
│       └── exports/                    # FreeCut writes exports here
└── media/
    └── <media_id>/
        ├── metadata.json               # fileName, size, duration, 1080x1920, codec, etc.
        ├── thumbnail.jpg               # extracted frame
        ├── <filename>                  # copied short
        └── cache/ai/transcript.json    # clip-local transcript envelope
```

### What `sync_freecut_project(...)` does

1. Finds an existing project for the video (`sourceVideoId` match) or generates a new 8-char base62 project ID.
2. Writes/updates `project.json` (name = YouTube title, 1080×1920@30 metadata, schema version 15).
3. For each generated short: copies it into the media library (reusing an existing media ID by filename), writes `metadata.json`, extracts a `thumbnail.jpg`, and links it in `media-links.json`.
4. For each short with a `.meta.json` source window, writes a **clip-local transcript** to `media/<id>/cache/ai/transcript.json` (FreeCut's `AiOutput<'transcript'>` envelope, schema version 1) so the editor's **Transcript sidebar tab** shows the captions (with word timings in media-native seconds) instead of running its own in-browser whisper.
5. Updates `index.json` (newest-first by `updatedAt`).

Everything is best-effort: failures return `None`/`[]` and never break clip generation.

---

## 7. Configuration Reference

All settings come from environment variables (loaded from `.env` via `python-dotenv`).

### Short Generator / Pipeline

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_PROVIDER` | `openai` | Local LLM backend: `openai` or `gemini` |
| `OPENAI_API_KEY` | — | OpenAI key for highlight ranking |
| `OPENAI_BASE_URL` | — | Optional compatible provider (Groq, DeepSeek, ...) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model |
| `GEMINI_API_KEY` | — | Gemini key when `LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model |
| `LOCAL_WHISPER_MODEL` | `base` | faster-whisper model (`tiny`/`base`/`small`/`medium`/`large-v3`/`turbo`) |
| `LOCAL_WHISPER_DEVICE` | `auto` | `auto` / `cpu` / `cuda` |
| `LOCAL_WHISPER_VAD_FILTER` | `false` | Enable VAD (off by default) |
| `LOCAL_WHISPER_VAD_PARAMETERS` | faster-whisper defaults | JSON VAD params (threshold, min speech/silence, speech pad) |
| `LOCAL_OUTPUT_DIR` | `output` | Where mp4s + caches land |
| `TEMPLATE` | `stage_solo_speaker` | Default cropping template |

### MuAPI (API mode, kept for reference)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MUAPI_API_KEY` | — | MuAPI key |
| `MUAPI_BASE_URL` | `https://api.muapi.ai/api/v1` | MuAPI endpoint |
| `MUAPI_POLL_INTERVAL` | `5` | Poll interval seconds |
| `MUAPI_POLL_TIMEOUT` | `600` | Poll timeout seconds |

### Web Editor (FreeCut)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PEXELS_API_KEY` | — | Powers the Stock / B-roll panel in the web editor (Pexels Video API) |

### Django (webui/settings.py)

| Setting | Value | Purpose |
|---------|-------|---------|
| `OUTPUT_DIR` | `BASE_DIR/output` | Output + FreeCut workspace |
| `FREECUT_DIST` | `BASE_DIR/vendor/freecut/dist` | Committed FreeCut build |
| `FREECUT_WORKSPACE` | `OUTPUT_DIR` | FreeCut workspace folder |
| Database | SQLite (`webui/db.sqlite3`) | Clip storage |

---

## 8. Project Structure

```text
AI-Youtube-Shorts-Generator/
├── main.py                       CLI entry point
├── manage.py                     Django entry point (web UI)
├── run_webui.bat                 Windows web UI launcher
├── requirements.txt              core deps
├── requirements-local.txt        deps for the local pipeline
├── .env.example                  env template
├── README.md                     project readme
├── Update.md / update2.md        older spec documents (historical)
├── newTemp.md                    canvas spec notes
├── webui/                        Django web UI
│   ├── settings.py               sqlite + OUTPUT_DIR / FREECUT_DIST wiring
│   ├── urls.py                   route table
│   ├── views.py                  download / transcribe / clip editor / generate / auto-generate / FreeCut app server
│   ├── models.py                 Clip (video_id, start_time, end_time)
│   ├── db.sqlite3                SQLite database
│   └── templates/webui/          base, home, clip_editor, editor_shell
├── vendor/freecut/               vendored FreeCut editor (source + committed dist build, MIT)
│   ├── src/                      FreeCut source (patched: base URL + build config only)
│   ├── dist/                     committed production build (served at /editor/)
│   ├── PRODUCT.md / README.md    editor docs
│   └── VENDORED.md               vendoring notes + fork patches
└── shorts_generator/
    ├── __init__.py               exports generate_shorts
    ├── config.py                 env / settings (LLM + Whisper + VAD + MuAPI)
    ├── highlights.py             LLM virality ranking + dedupe + chunking
    ├── pipeline.py               end-to-end orchestrator + generate_shorts()
    ├── progress.py               progress bars / spinners with ETA
    ├── freecut_projects.py       auto-create/update FreeCut projects + media + transcripts
    ├── downloader.py             API-mode download (MuAPI, kept for reference)
    ├── transcriber.py            API-mode transcription (MuAPI, kept for reference)
    ├── clipper.py                API-mode cropping (MuAPI, kept for reference)
    ├── muapi.py                  API-mode submit + poll wrapper (kept for reference)
    └── local/                    local pipeline backends
        ├── downloader.py         yt-dlp download + caching + cookie fallback
        ├── transcriber.py        faster-whisper transcription + .srt/.words.json cache
        ├── cookies.py            manual cookies.txt / browser cookie extraction
        ├── llm.py                OpenAI or Gemini client with retry/backoff
        └── clipper.py            ffmpeg cut + OpenCV template-based vertical crop + captions
```

---

## Summary of Key Capabilities

| Area | Capabilities |
|------|--------------|
| **Input** | YouTube URL, `file://` URL, or local path; 360–1080p |
| **Transcription** | faster-whisper (CPU/CUDA), word timestamps, VAD, caching |
| **Highlight selection** | Content-type detection, virality framework, long-video chunking, score-based dedupe, 30–60s window |
| **Rendering** | 9:16 1080×1920, two-pass face tracking, 2 templates, word-by-word captions, hook titles, widgets, blur-fill fallback |
| **LLM** | OpenAI or Gemini, retry/backoff, pluggable |
| **Web UI** | Download, transcribe, clip editor, one-click auto-generate, pipeline status, exports |
| **Editor** | Full multi-track NLE: timeline, effects, transitions, keyframes, audio, masks, local AI, export |
| **Integration** | Auto-created FreeCut projects, media library sync, clip-local transcripts |
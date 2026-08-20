**Version:** v1.0 (focused scope)
**Date:** 2026-08-14
**Owner:** Lemi Bekele

---

## 1. Product Overview

### 1.1 What it is

An **internal production tool** that converts one long-form video (podcast, interview, talk, tutorial) into a **posting-ready batch of vertical 9:16 clips** for a paid B2B clipping service. One operator (you) runs it to fulfill client orders.

### 1.2 What it is NOT (one-liner guardrails)

- NOT a consumer SaaS (no client accounts, no self-serve billing)
- NOT a general-purpose video editor (no timeline, no effects, no music library)
- NOT a social media scheduler (deferred)
- NOT a multilingual/dubbing tool (deferred)

### 1.3 The core job, in one sentence

**Client sends content → you return a post-ready clip pack within 48 hours, with \~10 minutes of hands-on work per video.**

### 1.4 Business context

The classic "Instagram theme page" (repost others' content) is dead in 2026 — Instagram's Dec 2025 algorithm shift crushed aggregator accounts 60–80% while boosting original creators. So the tool's value is **not** reposting; it's producing **original clips for clients who own the content**. Speed and clip-selection quality are the moat.

---

## 2. Goals & Success Metrics (speed-first)

| Metric                                   | Target                    | Competitor reference (2026)                                                  |
| :--------------------------------------- | :------------------------ | :--------------------------------------------------------------------------- |
| Time-to-first-clip (TTFC), 60-min video  | **< 10 min**              | Fastest 4–5 min; median 13 min; OpusClip \~25 min                            |
| Clips per hour (batch throughput)        | **≥ 30 clips/hr**         | n/a (local render advantage)                                                 |
| Order turnaround (video → deliverable)   | **< 48 hrs** incl. review | —                                                                            |
| Per-clip fix time (post client feedback) | **< 2 min**               | —                                                                            |
| Caption accuracy (English)               | **≥ 95%**                 | 8 of 9 tools clear 95%+                                                      |
| % of clips needing manual polish         | **< 20%**                 | OpusClip users report \~half need review; we aim better via stricter ranking |

**Architecture principle:** transcription-first + async is the _fastest_ architecture (benchmark-proven). Keep it. Do NOT add frame-level visual analysis (OpusClip's ClipAnything) — it's slower and targets gaming/sports, not your niche.

---

## 3. Product Principles (design tenets)

1. **"It's a form, not a timeline."** The only editor is a clip-polish _panel_ of property fields. No freeform editing surface. (Copied from Opus Clip's model.)
2. **Baked by default.** Captions and branding are rendered into pixels at render time. No separate caption step, no double-burn workflow.
3. **Speed is the feature.** Any feature that doesn't reduce time-to-deliverable is P2 or cut.
4. **Post-ready or don't ship.** A clip leaves the system only if the client can upload it with zero further work.
5. **Cut what doesn't feed the loop.** One operator, one screen, one happy path.

---

## 4. Scope & Non-Goals

### 4.1 In scope (v1)

Ingestion (URL/file/Drive) → transcription + diarization → LLM highlight ranking → branded render (baked captions + loudness) → clip polish panel → deliverable bundle.

### 4.2 Explicitly OUT of scope (v1)

- ❌ Social scheduler / auto-posting → P2
- ❌ Translation, dubbing, romanized captions → P2
- ❌ Full timeline editor, effects, transitions, keyframes, masks, audio EQ → **rejected**
- ❌ Local AI (TTS, music gen, scene detection) → **rejected**
- ❌ AI B-roll insertion → P2 (nice-to-have, adds scope)
- ❌ Client-facing self-serve accounts & billing → **rejected**
- ❌ Visual-scene / gaming / sports clipping → **rejected** (talking-head + podcast only)

### 4.3 Deferred to P2 (only if a client pays for it)

Auto-posting, analytics dashboard, multi-ratio export (9:16 + 1:1 + 4:5 in one pass), AI B-roll.

---

## 5. Target Architecture (after simplification)

```plain
INGEST ──► TRANSCRIBE + DIARIZE ──► RANK (LLM) ──► RENDER (branded, baked captions, loudness)
   │                                                                          │
   │ (URL / file / Drive / audio)                                             ▼
   └──────────────────────────────────────────►  CLIP POLISH PANEL (7 controls)
                                                        │
                                                        ▼
                                              DELIVERABLE BUNDLE (clips + captions/hashtags manifest)
```

### 5.1 REMOVE (cleanup before building)

| Component                                                                               | Action           | Reason                                                                   |
| :-------------------------------------------------------------------------------------- | :--------------- | :----------------------------------------------------------------------- |
| `vendor/freecut/` + `/editor/` routes + editor_shell                                    | **Delete**       | Full NLE, \~90% of its features irrelevant; replaced by the polish panel |
| `shorts_generator/freecut_projects.py`                                                  | **Delete**       | Depends on FreeCut; entire integration layer goes away                   |
| API mode ( `downloader.py`, `transcriber.py`, `clipper.py`, `muapi.py` at package root) | **Delete**       | "Kept for reference" = dead weight                                       |
| `MUAPI_*` config + `mode` param in pipeline                                             | **Delete**       | Only `local` mode remains                                                |
| `burn_captions` default `False`                                                         | **Flip to True** | Baked-by-default principle                                               |

### 5.2 KEEP (already aligned)

`pipeline.py` + `generate_shorts()`, `highlights.py` (virality framework/chunking/dedupe), `local/clipper.py` (two-pass face-track + templates + captions), `.srt`/ `.words.json` caching, CLI + Python API, cookie fallback chain, Django home/clip-editor views, byte-range serving.

---

## 6. Core Workflow (the one happy path)

1. **Ingest** — operator pastes YouTube URL, drops a file, or pastes a Google Drive/Dropbox link.
2. **Transcribe + diarize** — Whisper word-timestamps + speaker labels, cached.
3. **Rank** — LLM scores highlights (0–100) with hook + virality reason; auto-split long videos.
4. **Approve** — operator reviews ranked list in the web UI: toggles brand-safety, sets clip length, picks the client brand preset.
5. **Render** — clips render in parallel: branded captions baked, logo/handle overlay, loudness normalized.
6. **Polish** — operator opens any clip that needs it in the **Clip Polish Panel**, fixes hook/captions/trim/reframe, re-renders in seconds.
7. **Package** — bundle clips + caption/hashtag manifest into one zip; upload to Drive; send link.

---

## 7. Functional Requirements

Legend: ✅ Have · 🟡 Partial · 🔴 Build

---

### 7.1 P0 — Ingestion

**FR-1.1 File upload** 🔴
Operator can upload a raw video file (mp4/mov/mkv/webm) through the web UI.

- AC: A 2 GB mp4 uploads without crashing; streaming/resumable upload, not a single POST.

**FR-1.2 Cloud-link ingestion** 🔴
Operator can paste a Google Drive / Dropbox / WeTransfer link; system downloads it.

- AC: Given a valid Drive share link, the source lands in `output/` and proceeds to transcription.

**FR-1.3 URL + local path** ✅
YouTube URL, `file://`, and local filesystem path all accepted (already works).

**FR-1.4 Audio-only input** 🔴
Audio-only (mp3/wav/m4a) is accepted and rendered against a static cover/thumbnail frame.

- AC: Given an mp3, the system produces 9:16 clips with a static background + captions.

**FR-1.5 Cookie fallback for gated YouTube** ✅
Already implemented; keep as-is.

---

### 7.2 P0 — Transcription & Diarization

**FR-2.1 Word-level transcription + caching** ✅
faster-whisper with word timestamps; `.srt` + `.words.json` cache; re-runs skip.

- AC: Re-running the same video skips transcription entirely.

**FR-2.2 Speaker diarization** 🔴
Identify who is speaking, per segment, with speaker labels.

- AC: A 2-speaker podcast yields `segments[]` each tagged with `speaker_id`.
- AC: `podcast_split_screen` template frames the _correct_ speaker per panel using diarization.
- Suggested: pyannote-audio or WhisperX (keep it local).

**FR-2.3 Language auto-detect** ✅ (partial)
Auto-detect works; hook/captions must render in the detected language.

- AC: Non-English source produces non-English hooks and captions.

---

### 7.3 P0 — Highlight Selection (already strong)

**FR-3.1 Virality scoring + hook + reason** ✅
8-signal framework, 0–100 score, `hook_sentence`, `virality_reason`.

**FR-3.2 Long-video chunking + dedupe** ✅

> 30 min auto-split into 10-min overlapping chunks; >50% overlap dedupe keeps higher score.

**FR-3.3 Brand-safety filter** 🔴
Operator toggle: exclude profanity / sensitive topics before scoring.

- AC: With "no profanity" on, selected clips contain no flagged words.

**FR-3.4 Clip-length control** 🟡 (partial)
`min/max` seconds exist. Extend to per-client presets (15s/30s/60s targets).

- AC: With max=60, no clip exceeds 60s and no clip cuts mid-sentence.

---

### 7.4 P0 — Rendering (branded, baked, loud)

**FR-4.1 Face-tracked 9:16 reframe + blur-fill** ✅
Two-pass motion-smoothed face tracking, blurred-fill fallback.

**FR-4.2 Templates (solo + split-screen)** ✅
Keep both; split-screen gains diarization (FR-2.2).

**FR-4.3 Baked word-synced captions** 🟡
`burn_captions=True` becomes the **default**. Captions read from transcript, word-synced.

- AC: Every rendered clip has captions burned in with zero extra steps.

**FR-4.4 Caption style config** 🔴
Font, color, size, position, keyword-highlight color, emoji toggle — all configurable (currently hardcoded `#ff914d`).

- AC: Operator changes caption color once; all clips for that preset use it.

**FR-4.5 Logo / @handle overlay** 🔴
Optional logo image + handle text overlay, position configurable.

**FR-4.6 Safe-area margins** 🟡 (verify)
Canvas spec already reserves top/bottom zones; verify text never sits under TikTok/Reels UI chrome.

- AC: Preview grid shows platform safe zones; captions/hooks stay inside.

**FR-4.7 Loudness normalization** 🔴
One `loudnorm` (or `loudnorm`+limiter) pass in the mux step (already re-encoding there).

- AC: Output loudness within platform-acceptable LUFS; no clipping.

---

### 7.5 P0 — Clip Polish Panel (the editor)

**This replaces FreeCut.** A single-screen, property-based editor. _Form, not timeline._

| Control               | Description                                                                                | Status                    |
| :-------------------- | :----------------------------------------------------------------------------------------- | :------------------------ |
| **Trim (word-level)** | Click transcript word → set start; click word → set end                                    | ✅ Have                   |
| **Hook title**        | Editable text field, re-rendered into top safe zone                                        | 🔴                        |
| **Captions**          | Fix transcript words + style (font/size/color/position) + keyword highlight + emoji on/off | 🔴                        |
| **Reframe nudge**     | If tracking missed, re-center on a face/region or pick speaker                             | 🔴                        |
| **Overlays**          | Logo/@handle position, progress-bar on/off, safe-zone grid preview                         | 🔴                        |
| **Brand template**    | Save all settings as a named preset, auto-applied per client                               | 🔴                        |
| **Re-render**         | Apply edits → regenerate this one clip in seconds                                          | 🟡 ( `.meta.json` exists) |

**FR-5.1 Per-clip "Edit" view** 🔴
Each generated clip links to an edit view exposing the 7 controls.

- AC: Operator can edit hook text and caption words for a single clip and re-render only that clip.

**FR-5.2 Re-render single clip** 🔴
Re-render reads `ClipOverride` (see §8) and reuses the source + transcript cache.

- AC: A caption-text fix re-renders in < 30s without re-transcribing or re-cutting other clips.

**FR-5.3 Brand template** 🔴
Save panel settings (captions style, overlays, template, length prefs) as a named preset; select it when generating.

- AC: Switching presets re-renders clips with the new brand, no re-scoring.

**FR-5.4 Optional 360p preview render** 🟡
Fast low-res render for the edit loop; full render only on "export." (Optimization; ship after FR-5.1/5.2 if needed.)

---

### 7.6 P0 — Delivery & Packaging

**FR-6.1 Auto caption + hashtags per clip** 🔴
LLM writes a full post caption + hashtags + title per clip (not just the hook).

- AC: Every clip ships with a ready-to-paste caption.

**FR-6.2 Deliverable bundle** 🔴
One zip containing: all clip mp4s + a `manifest.csv/json` with `{clip_file, hook, caption, hashtags, start, end, score}`.

- AC: Client can hand the zip to a VA and post with zero extra work.

**FR-6.3 Cloud delivery** 🔴
Upload bundle to Google Drive/Dropbox; produce a share link.

- AC: One click produces a client-facing download link.

---

### 7.7 P1 — Scale & Operations (build after first paying client)

- **FR-7.1 Job queue** 🔴 — Celery/RQ so multiple videos process without blocking the UI.
- **FR-7.2 Per-client workspaces** 🔴 — `output/clients/<name>/` isolation + saved brand preset.
- **FR-7.3 Client review loop** 🔴 — share a link; client approves/rejects/comments.
- **FR-7.4 Job-done notification** 🔴 — email/DM when a batch is ready.
- **FR-7.5 Storage cleanup** 🔴 — auto-delete old source files after N days.

---

### 7.8 P2 — Deferred (only if a client pays)

- FR-8.1 Auto-posting to TikTok/Reels/Shorts on a schedule
- FR-8.2 Analytics (views per clip → prove ROI)
- FR-8.3 Multi-ratio export (9:16 + 1:1 + 4:5)
- FR-8.4 AI B-roll insertion

---

## 8. Data Model

```latex
Client
  id, name, email, drive_folder, brand_preset_id (FK)

BrandPreset
  id, name, template (stage_solo_speaker|podcast_split_screen),
  caption_font, caption_color, caption_accent, caption_size, caption_position,
  keyword_highlight (bool), emoji (bool),
  logo_path, handle, progress_bar (bool),
  min_clip_seconds, max_clip_seconds, brand_safety (bool)

SourceVideo
  id, source_type (url|file|drive|audio), source_ref, title,
  srt_path, words_path, diarization_path, status (downloaded→transcribed→ranked→rendered)

Clip
  id, video_id (FK), start_time, end_time, score, hook_sentence, virality_reason,
  template, status (pending→rendered→delivered)

ClipOverride (one-to-one with Clip; empty = use auto/preset defaults)
  clip_id (FK), trim_start, trim_end,
  hook_text, caption_text_override,
  caption_style_override (JSON: color/size/position/highlight),
  reframe_override (JSON: center_xy | speaker_id),
  overlay_override (JSON: logo_pos, progress_bar)
```

**Note:** current `Clip` model already has `video_id/start_time/end_time` — extend it, don't rewrite.

---

## 9. Non-Functional Requirements

- **Performance:** TTFC < 10 min (60-min source); single-clip re-render < 30s; ≥ 30 clips/hr batch.
- **Reliability:** transcription cache invalidation already handled; render retries with clear errors; no orphan temp files (OpenCV temp-copy cleanup already present).
- **Privacy/local-first:** everything local except the highlight-ranking LLM call. State this to clients ("your raw footage never leaves our machine").
- **Rights:** operator warrant clause in client terms — client owns or licenses the source content.

---

## 10. Build Order (milestones)

| Milestone                | Scope                                                                                                      | Exit criteria                                                   |
| :----------------------- | :--------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| **M0 — Cleanup**         | Delete FreeCut, API mode, freecut_projects.py; flip `burn_captions=True` default                           | App still runs end-to-end, smaller codebase                     |
| **M1 — Core production** | FR-1.1/1.2/1.4 (ingestion), FR-2.2 (diarization), FR-4.4/4.5/4.7 (brand + loudness), FR-3.3 (brand-safety) | Can ingest a client's Drive link and render branded, loud clips |
| **M2 — Polish panel**    | FR-5.1–5.3 (edit view, re-render, brand template), FR-4.6 verify                                           | Can fix any clip in < 2 min, post-ready                         |
| **M3 — Delivery**        | FR-6.1–6.3 (captions/hashtags, bundle, Drive upload)                                                       | One click → client-facing download link                         |
| **M4 — Scale (P1)**      | FR-7.1–7.5                                                                                                 | Can run 3+ clients concurrently                                 |

**"First client ready" = M0 + M1 + M2 + M3.**

---

## 11. Definition of Done — "post-ready" clip

A clip is done only when ALL are true:

1. 9:16, 1080×1920, text inside safe margins
2. Captions accurate + word-synced + styled (no obvious errors)
3. Hook/title on screen within first 3s
4. Branded (logo/handle/colors consistent)
5. Loudness normalized
6. 30–60s, clean in/out, never mid-sentence
7. No watermark, H.264 + AAC, faststart

---

## 12. Risks & Open Questions

- **Diarization accuracy** on overlapping/soft voices — verify on a real 2-speaker podcast before promising split-screen.
- **Drive/Dropbox download** rate limits and auth — confirm link types that work without OAuth.
- **Re-render speed** for the polish loop — if > 30s, add 360p preview (FR-5.4).
- **Single-clip caption edit** requires a per-clip transcript offset — already have `.meta.json` source window; confirm it maps correctly after re-cut.

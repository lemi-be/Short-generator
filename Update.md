# Technical Specification Document: Short-Form Video Clipper & Adaptive Layout Engine

---

## 1. Executive Summary & Goals

This document specifies the technical architecture, dynamic template selection algorithm, and rendering engine upgrades for the **Short-Form Video Clipper Application**.

### Primary Objectives
1. **Adaptive Aspect Ratio Handling:** Convert any input source video (16:9, 1:1, 4:5, 9:16) into a standardized **9:16 portrait video** for short-form platforms (TikTok, Instagram Reels, YouTube Shorts).
2. **Category-Driven Template Selection:** Allow users to manually select a high-level **Content Category** (e.g., *Gaming*, *Podcast*, *Education*) while an automated engine selects the best visual layout using heuristic rules (aspect ratio, face count, scene saliency).
3. **High-Performance FFmpeg Rendering:** Eliminate OpenCV Python frame-by-frame processing loops in favor of fast, native **FFmpeg `-filter_complex`** single-pass rendering.
4. **Asynchronous Execution:** Process rendering tasks out-of-band using background job workers to prevent HTTP request timeouts.

---

## 2. Updated Pipeline Architecture

```text
       ┌─────────────────────────────────────────────────────────┐
       │                   Home Page / Input                     │
       └───────────────────────────┬─────────────────────────────┘
                                   │
                                   ▼
                       POST /download/<video_id>
                                   │ (yt-dlp)
                                   ▼
                        OUT_DIR/source_<id>.mp4
                                   │
         ┌─────────────────────────┴─────────────────────────┐
         │                                                   │
         ▼                                                   ▼
POST /transcribe/<id>                             ffprobe Metadata Extraction
  ├─ faster-whisper (word_timestamps=True)           ├─ Extract width, height, aspect ratio
  └─ Generates source_<id>.srt & .ass                └─ Store metadata in memory / DB
         │                                                   │
         └─────────────────────────┬─────────────────────────┘
                                   │
                                   ▼
                       GET /clip-editor/<id>
  ├─ Interactive SRT transcript timeline
  ├─ User picks Clip Start & End times
  ├─ User picks Content Category (e.g., "gaming_entertainment")
  ├─ Engine auto-resolves best template via heuristic selection (or user overrides)
  └─ POST /add/<id> ──► Saves Clip & Template Config to SQLite
                                   │
                                   ▼
                      POST /generate/<id> (Async)
  ├─ Immediately enqueues job to background worker (e.g., Celery / RQ / ThreadPool)
  ├─ Returns HTTP 202 with `job_id` for UI status polling
  └─ Worker runs single-pass FFmpeg command:
       Scale + Crop/Blur + Burn ASS Subtitles + Remux Audio natively
                                   │
                                   ▼
                       OUT_DIR/final_clip_<clip_id>.mp4
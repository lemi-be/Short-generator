# Technical Specification: Context-Aware Video Intelligence & Smooth Auto-Cropping Engine

---

## 1. Executive Summary & Core Philosophy

This specification upgrades the video processing pipeline from naive, frame-by-frame face tracking (which causes jitter and lost scene context) to a **Two-Pass Context-Aware Analysis Engine**. 

### Core Operating Philosophy
1. **Intelligence Before Execution:** Computer vision and speaker detection act as a *pre-scan pass* to understand the scene geometry, identify who is speaking, and calculate required object margins *before* any cutting occurs.
2. **Context Preservation Over Face Zoom:** The engine evaluates the union of active speakers and relevant context objects (e.g., laptops, whiteboards, secondary subjects). If a scene's context exceeds vertical 9:16 boundaries, the engine defaults to a **Padded Blurred Fit** rather than cutting off crucial visual elements.
3. **Cinematic Camera Smoothing:** Raw detection coordinates are filtered through an **Exponential Moving Average (EMA)** camera math layer to eliminate micro-jitter and produce smooth tripod/pan movements.

---

## 2. Updated Architecture Pipeline

```text
                                  ┌──────────────────────────┐
                                  │   Input Video (.mp4)     │
                                  └─────────────┬────────────┘
                                                │
                                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PASS 1: PRE-SCAN & SCENE UNDERSTANDING (Low FPS)                                       │
│                                                                                        │
│  ┌───────────────────────────────┐          ┌──────────────────────────────────────┐   │
│  │ Audio Diarization             │          │ Visual Detection (YOLOv8 @ 1-2 FPS)  │   │
│  │  - Active Speaker Timestamps  │          │  - Person / Face Bounding Boxes      │   │
│  │  - Speaker IDs (A, B, etc.)   │          │  - Context Objects (laptop, UI, etc) │   │
│  └───────────────┬───────────────┘          └──────────────────┬───────────────────┘   │
│                  │                                             │                       │
│                  └──────────────────────┬──────────────────────┘                       │
└─────────────────────────────────────────┼──────────────────────────────────────────────┘
                                          │
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PASS 2: SPATIAL FUSION & LAYOUT RESOLUTION                                             │
│                                                                                        │
│  1. Spatial Union: B_target = B_speaker ∪ B_object                                     │
│  2. Aspect Check: Fits in 9:16 vertical slice?                                         │
│     ├─ YES ──► Mode: SMART_DYNAMIC_CROP                                                │
│     └─ NO  ──► Mode: PADDED_BLURRED_FIT (Preserves full width context)                 │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ PASS 3: ANTI-JITTER SMOOTHING & FFMPEG RENDERING                                       │
│                                                                                        │
│  1. Apply EMA Filter: C_t = α * C_{t-1} + (1 - α) * D_t                                │
│  2. Generate Smooth Crop Trajectory Keyframes                                          │
│  3. Execute Single-Pass FFmpeg Filtergraph                                             │
└─────────────────────────────────────────┬──────────────────────────────────────────────┘
                                          │
                                          ▼
                               ┌──────────────────────────┐
                               │ Output Short (.mp4 9:16) │
                               └──────────────────────────┘
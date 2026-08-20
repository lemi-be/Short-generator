# PRD: Fast-Path Clip Production Line (v3 — speed-focused)
### Internal tool spec, built for one operator delivering paid clips fast — not a general-purpose app

**Status:** Draft v3 — supersedes v1/v2 (business framing stays the same; this version is about speed and scope)

**Core problem this version fixes:** the current build is a general-purpose open-source video pipeline + NLE, not a tool shaped around your specific job. It has real capability but also real bloat you didn't ask for, and that bloat costs you time and decisions on every episode. This PRD defines the tool as **the minimum path from raw video to a delivered, on-brand clip batch**, then audits what you already have against that minimum.

---

## 1. What a paying client actually needs (the deliverable spec)

Strip away everything else — this is the only thing you're actually being paid for:

- **Format:** clean 9:16 vertical MP4, correct duration (15–60s), no dead air, opens with a hook in the first few seconds.
- **Captions:** accurate, synced, readable on mute, styled consistently in *that client's* look (font/color/position) — not a generic default.
- **Framing:** speaker stays in frame, no awkward crops, works whether it's one speaker or two.
- **Branding (if applicable):** consistent small touch per client — a lower-third, logo corner, or color accent that makes their clips recognizable as *theirs* across episodes.
- **Consistency across a batch:** if you deliver 8 clips from one episode, they should look like they came from the same production, not 8 different experiments.
- **Turnaround:** fast and predictable — this is your main competitive lever against slower agencies/freelancers, so it matters as much as visual quality.
- **Delivery:** files clearly named and organized enough that the client can immediately tell which clip is which and post it — not a folder of `output_final_v2.mp4`.

Notice what's **not** on this list: LUTs, color grading, blend modes, keyframed motion graphics, transitions, multi-track compositing, Lottie animation, AI-generated music, text-to-speech, scene detection. None of that is what you're being paid for. Every hour spent making those work well is an hour not spent on the six bullets above.

---

## 2. What you need to be fast (the operator spec)

This is the part the last version skipped. Your actual job, once per client and then per episode, is:

0. **(Once per client)** Create a project: name, caption style, branding. Under a minute, never repeated for that client.
1. Watch/skim the transcript, mark clip boundaries. *(your judgment — can't be automated, shouldn't be rushed)*
2. Trigger render for all marked clips at once. *(should be one action, not one-per-clip)*
3. Confirm captions and framing look right, fix the rare bad word-timing or crop. *(quick pass, not fine-tuning)*
4. Apply the client's saved look (caption style + branding) — inherited automatically from the project created in step 0, never chosen per episode.
5. Export and package for delivery. *(one action, correctly named files, ready to send)*

**Target: under ~20 minutes of your hands-on time** per episode to go from "raw video in" to "batch ready to deliver," for a typical 5–8 clip batch, once the curation itself is done. Curation time (step 1) is separate and will vary — that's the part that's genuinely your value-add and shouldn't be rushed. Everything else should be close to friction-free.

**What breaks this target, based on the system as documented:**
- Anything that requires you to reconfigure settings per episode instead of per client (currently: no client concept exists at all in the data model — clips are tied only to `video_id`).
- Anything that requires you to leave the transcript-marking screen to do routine work.
- Any UI surface you have to visually scan past or consciously ignore to find the three buttons you actually use.
- One-clip-at-a-time actions where a batch action would do.

---

## 3. Technical audit: what to keep, hide, or build

Based on your system documentation. Organized by the two big pieces: the Python pipeline + Django UI, and the vendored FreeCut editor.

### 3.1 Short Generator pipeline + Web UI

| Keep (already serves the fast path) | Hide or remove (bloat, adds friction/confusion) | Build (missing, needed for speed) |
|---|---|---|
| Local download (yt-dlp) | `api` mode (MuAPI) — dead weight if you're not using it; remove rather than "keep for reference," it's config surface you'll never touch | **Client entity** in the data model — right now clips only know about `video_id`, not which paying client they belong to |
| Local transcription (faster-whisper, word timestamps, caching) | "Auto-generate" one-click LLM pipeline as the *default*, front-and-center CTA — demote it to an optional/hidden mode since it's not your workflow | **Per-client presets**: caption style (font/color/position), branding overlay, default template — saved once, auto-applied every time, never re-chosen per episode |
| Transcript-click clip marking | Pipeline-status-chain UI (Downloaded → Transcribed → Clips → Generated) — nice for a dashboard, irrelevant to actually doing the work fast | **Batch clip marking**: mark all clips for an episode in one pass, then one "render all" action — not render-per-clip |
| Face-tracked 9:16 reframe + 2 templates | | **Delivery packaging**: auto-rename files by client/episode/clip index, zip or organize into a client folder — currently the pipeline stops at raw export files in `output/`, with no packaging step |
| Auto-captioning from real transcript | | |

### 3.2 FreeCut editor (the vendored NLE)

This is where the bulk of the wasted-time risk lives. FreeCut is a **full general-purpose multi-track NLE** — closer to a lightweight Premiere than a clip-finishing tool. Almost none of its feature surface is what a 30–60s social clip needs, and by default you have to look at (or consciously ignore) all of it every time you open the editor.

**Keep — this is the actual job:**
- Basic trim/split on a simple timeline
- Caption text layer: position, font, color, editable text
- Crop/reframe check and manual override
- Basic export to MP4, H.264
- Waveform for precise trim points
- Undo/redo

**Hide or disable — general-NLE features that don't serve a 30–60s branded clip, and are pure decision-friction on every episode:**
- Full effects suite: blur variants, color grading (curves, wheels, LUTs, gradient maps), distortion filters, stylize filters, 25 blend modes
- Masks, pen paths, full keyframe bezier/dopesheet animation system, procedural motion modifiers
- Multi-track / multi-sequence / compound clip workflows — a single clip doesn't need this
- **Local AI panel entirely** (on-device transcription, AI captioning VLM, scene detection, Kokoro TTS, MusicGen) — you already have the real transcript from the Python pipeline; this whole panel is redundant and likely just adds load time
- Lottie animation editing, ProRes decode/proxy generation — media edge cases you don't hit
- Multi-workspace switcher, project ZIP export/import, soft-delete/trash/restore — team/long-term project management ceremony, irrelevant for a single operator turning around clips same-day
- Transitions library, color scopes (waveform/vectorscope/histogram) — pro tooling you won't use per-clip

**Build — the single highest-leverage technical change:**
- A **stripped "Quick Clip" view**: on opening a rendered clip, show only preview + trim handles + caption style panel (with the client's preset pre-applied) + one export button. Everything above stays available in an "advanced" mode if you ever need it, but it's not what loads by default. This is a UI configuration/hide job, not new engineering — the features already exist in FreeCut, they just need to stop being in your way.

---

## 4. Build priority (ordered by speed impact vs. effort)

**P0 — do first, low effort, immediate time savings:**
1. Hide the unused FreeCut panels (effects, masks, keyframes, Local AI, multi-workspace, transitions, scopes) — config-level, not new code.
2. Demote "Auto-generate" from the default homepage CTA.
3. Remove/hide the `api` (MuAPI) mode entirely from the UI.

**P1 — the real customization work:**
4. **Client project as the entry point.** Every episode gets added *into* a client project, not created loose and tagged after the fact. Creating a project is where caption style, branding, and template get set once — the data model needs a Client/Project entity that episodes belong to, and a fast (under a minute) project-creation flow as the literal first screen of the app.
5. Batch clip-marking and batch-render for a whole episode in one pass.
6. Build the "Quick Clip" simplified export view in FreeCut.

**P2 — once you have real client volume and know what actually matters:**
7. Delivery packaging (auto-naming, zip/folder per client).
8. Anything else — resist adding it until a real client interaction asks for it.

---

## 5. Non-goals (explicitly do not build)

- Do not build toward a general-purpose editor experience — every FreeCut feature you re-expose is a feature you have to visually navigate around next time, forever.
- Do not make the optional LLM highlight-suggestion mode a priority — it's not your bottleneck and it's not your pitch.
- Do not build multi-user/client-facing UI — you are the only user of this tool for the foreseeable future.
- Do not polish visual features (transitions, motion graphics, color grading) speculatively — only build what a specific paying client actually asked for.

---

## 6. Success metric

**Operator time per episode, raw video to delivered batch — target under ~20 minutes excluding curation time.** Track this for real, per episode, starting now. If a step is eating more time than it should, that's your signal for what to fix next — not a feature that seems like it'd be nice to have.

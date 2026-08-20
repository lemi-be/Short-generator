# Pipeline structure: raw video to delivered clips

Seven stages, start to end. Red/amber/green below match the tally-color system in the design language doc — same state language, same meaning, everywhere in the tool.

---

## Overview

```
[0] Select or create client project   ← one-time setup per client
      ↓
[1] Add episode                       ← scoped to that project
      ↓
[2] Transcribe locally
      ↓
[3] Mark clips manually   ← the only manual step — your judgment
      ↓
[4] Batch render clips
      ↓
[5] Quick clip polish
      ↓
[6] Package & deliver
```

**One rule this structure enforces:** everything except stage 0 (done once per client) and stage 3 (your judgment, every episode) is automated. Stage 0 exists so the automation in stages 1, 2, 4, 5, and 6 has something to inherit from — without it, you'd be re-deciding caption style, branding, and naming on every single episode instead of once per client.

---

## Stage 0 — Select or create client project

| | |
|---|---|
| **Input** | Nothing, for a new client — just a name. For a returning client, one click to select their existing project |
| **What happens** | A new project sets caption style (font/color/position) and branding (logo/lower-third) once. Everything downstream — every episode, every clip, every export — inherits these automatically | 
| **Output** | A project shell ready to receive episodes |
| **Who does it** | You, once per client — should take under a minute |
| **Tally state** | Not applicable — this is setup, not a work item |

---

## Stage 1 — Add episode

| | |
|---|---|
| **Input** | A YouTube URL, or a local video file, added to an existing client project |
| **What happens** | The tool downloads the source (if needed) and queues it for transcription |
| **Output** | A raw video file, scoped to that client's project, ready to transcribe |
| **Who does it** | Automated |
| **Tally state** | Amber while downloading, green once queued |

---

## Stage 2 — Transcribe locally

| | |
|---|---|
| **Input** | The raw video from stage 1 |
| **What happens** | Local transcription with word-level timestamps, cached so you never pay for or wait on this twice for the same file |
| **Output** | A synced, searchable transcript |
| **Who does it** | Automated, free, local |
| **Tally state** | Amber while transcribing, red once ready — it's now waiting on you |

---

## Stage 3 — Mark clips manually

| | |
|---|---|
| **Input** | The synced transcript |
| **What happens** | You read the transcript and mark in/out points for every clip worth pulling — this is the curation step no algorithm does for you |
| **Output** | A list of marked clip ranges for this episode |
| **Who does it** | **You.** The only manual stage in the pipeline, on purpose |
| **Tally state** | Red until every worthwhile moment is marked |

---

## Stage 4 — Batch render clips

| | |
|---|---|
| **Input** | All marked clip ranges from stage 3, rendered together in one action |
| **What happens** | Each marked range is cut, reframed to 9:16 with face tracking, and captioned from the real transcript timestamps |
| **Output** | A batch of rendered vertical clips, unpolished |
| **Who does it** | Automated |
| **Tally state** | Amber while rendering, green when the batch is ready to review |

---

## Stage 5 — Quick clip polish

| | |
|---|---|
| **Input** | The rendered batch from stage 4 |
| **What happens** | You step through each clip in the lightweight review view — client's caption style and branding are already applied, you're confirming, not configuring. Full editor is one click away if a clip genuinely needs it, but that's the exception |
| **Output** | Confirmed, client-branded clips |
| **Who does it** | Mostly a fast confirmation pass by you; the actual styling work is automated via saved client presets |
| **Tally state** | Red per clip until confirmed, green once you've stepped through the batch |

---

## Stage 6 — Package & deliver

| | |
|---|---|
| **Input** | Confirmed clips from stage 5 |
| **What happens** | Files are renamed and organized (already done automatically at render time), bundled, and marked delivered |
| **Output** | A delivered batch, ready in the client's hands |
| **Who does it** | Automated — one action |
| **Tally state** | Green |

---

## What this structure is actually optimizing

Every stage except 0 and 3 exists to be invisible. Stage 0 is the one place spending a little extra care up front pays off repeatedly — a well-set-up project (right caption style, right branding) means stages 1, 2, 4, and 6 never need your attention again for that client. If you ever find yourself spending real time in stages 1, 2, 4, or 6, that's a signal either something's misconfigured, or the client's project preset needs fixing at the source. Time and attention should concentrate almost entirely in stage 3 (judgment) and a fast pass through stage 5 (confirmation), which is exactly where the operator-time budget in the technical PRD (~20 minutes per episode, excluding curation) assumes it will go.

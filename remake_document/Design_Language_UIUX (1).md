# Design language & UI/UX spec
### For the fast-path clip production tool — every decision justified by speed, not aesthetics for its own sake

**Status:** Draft v1
**Test for every design decision in this document:** *does this reduce clicks or time-on-task for a routine episode?* If the answer is no, or "it looks nicer," cut it. This tool has exactly one user and one job: get you from raw video to a delivered batch faster than last time.

---

## 1. Design philosophy

- **This is a cockpit, not a showroom.** You will look at this tool for hours across many episodes. Optimize for a person who already knows where everything is, not a first-time visitor. No onboarding tours, no explanatory empty states beyond what's functionally needed, no decorative flourishes competing for attention with the transcript you're actually reading.
- **One screen, one job.** Each screen should let you finish its task without navigating away mid-task. If you have to leave the marking screen to change a caption color, that's a design failure, not a missing feature.
- **Status should be readable without reading.** Color and position tell you what needs your attention before you've processed a single word of text. This is the single biggest lever for a tool you'll glance at dozens of times a day.
- **Advanced power stays out of the way until asked for.** Everything FreeCut can do that you rarely need (effects, keyframes, multi-track) still exists — it just isn't the first thing you see. Progressive disclosure, not deletion.

---

## 2. Where this design comes from

Grounding choice, not a generic dark-mode template: **broadcast control room tally lights.** In a live studio, a red light means "this is live, act now," green means "ready to go," amber means "coming up / processing." Directors read the whole room's state in a glance, from across the room, without reading a single label. That's exactly the problem this tool has — you're triaging state across many clips and clients — so it borrows the same color language on purpose, not decoratively.

---

## 3. Token system

### Color

A dark canvas — the actual working condition of a video editor, not a stylistic choice. Base neutrals are warm graphite (not pure black/gray, which reads sterile and fights skin-tone footage on preview).

| Token | Hex | Use |
|---|---|---|
| `--bg-void` | `#17161A` | Base canvas |
| `--bg-panel` | `#201F24` | Cards, panels |
| `--bg-panel-raised` | `#2A2930` | Hover / active surfaces |
| `--text-primary` | `#F0EFE9` | Primary text |
| `--text-secondary` | `#9A968E` | Secondary / metadata text |
| `--text-muted` | `#625F58` | Disabled, hints |
| `--line-hairline` | `#35333A` | Borders, dividers |
| `--tally-red` | `#E4483B` | Needs you — unmarked, action required, blocking |
| `--tally-amber` | `#E8A23C` | In progress — rendering, processing |
| `--tally-green` | `#5FBF6E` | Done — ready to review or deliver |

**Rule:** these three tally colors are the *only* colors allowed to carry meaning anywhere in the tool. If you're tempted to add a fourth status color, that's a sign the state doesn't need its own color — collapse it into one of the three.

### Typography

Two roles, deliberately different faces — because you do two different kinds of reading in this tool, and one face for both would serve neither well:

- **Transcript body** (the screen you'll stare at longest, doing real reading to find good moments): a humanist serif or warm-readable sans, 16–17px, line-height 1.6. Optimized for scanning long text comfortably, not for UI chrome.
- **UI chrome & labels** (buttons, panel titles, menus): a neutral grotesque (Inter, system-ui, or similar), 13px, medium weight. Gets out of the way.
- **Timecodes, durations, filenames, hotkeys**: monospace (JetBrains Mono or similar), 12px, tabular figures. This is the one non-negotiable typographic choice — every professional NLE uses monospace for timecodes because your eye needs to line up digits instantly, not read them like prose.

**Weight discipline:** two weights only, regular and medium. No bold-for-emphasis anywhere — emphasis comes from the tally color system, not font weight.

### Spacing & density

Dense, not spacious. This isn't a marketing page with room to breathe — it's a workspace where you want maximum information visible without scrolling. Favor compact list rows and tight panel padding over generous whitespace, but never so dense that hit targets for click/tap actions shrink below comfortable size.

---

## 4. The signature element: the tally rail

A **4px vertical strip along the left edge of every screen**, colored by that screen's dominant state:

- Red if there are unmarked or unreviewed clips waiting on you.
- Amber if something is actively rendering.
- Green if everything on this screen is done and ready to send.

You should be able to tell, from a glance at the edge of the screen (even peripherally, even from across the room), whether this client's work needs you right now. This is the one deliberately memorable element — everything else in the tool stays quiet and disciplined around it.

---

## 5. Screens

### 5.1 Home — client projects

The entry point. One row per client project, sorted by tally state (red first).

```
┌─ tally rail
│  [●red]  Acme Podcast          3 unmarked · 2 rendering    →
│  [●amber] Weekly Tech Show      —          · 5 rendering    →
│  [●green] Founders Hour         all clear                   →
│                                                    [+ New project]
```

- Clicking a row goes straight into that client's active work (marking, if clips are unmarked; review, if clips are rendering/done) — never a generic dashboard detour.
- "New project" is the only other action on this screen. Everything else lives one level in.

### 5.1a New project — one-time setup per client

Deliberately the smallest, fastest screen in the tool. It exists once per client and should never feel like a form.

```
┌─ tally rail
│  New project
│  Client name:  [________________]
│  Caption style: [font ▾] [color ▾] [position ▾]
│  Branding:      [upload logo]  or  [skip for now]
│                                              [Create project →]
```

- Three fields, one optional. Nothing here blocks creation — "skip for now" is always valid, since a project with defaults is still faster than no project.
- Template choice and anything else deferrable is not asked here — it defaults, and can be changed later from inside the project without re-visiting this screen.
- Landing here should feel like "give it a name and go," not onboarding.

### 5.2 Mark clips — the core daily screen

This is where you spend most of your time, so it gets the most restraint. Full-height transcript on the left, minimal marking controls on the right. No chrome competing with the text. Always entered from inside a client project (5.1) — the header names the project so caption style and branding are implicitly already settled, never a decision made on this screen.

```
┌─ tally rail
│  Acme Podcast — Ep. 42                          [I] mark in  [O] mark out
│ ─────────────────────────────────┬──────────────
│  00:14:02  ...and that's when     │  Clips (3)
│            we realized the        │  ┌────────────
│            whole model was        │  │ 00:14:02–00:14:38
│            wrong. ▸ [in]          │  │ "that's when we..."
│  00:14:38  So we scrapped it ◂[out]│  └────────────
│            and started over...    │  ┌────────────
│  ...                              │  │ 00:22:10–00:22:51
│                                    │  └────────────
│                                    │
│                                    │  [Render all marked →]
```

- Marking is keyboard-first: `I` sets in-point at your cursor/scroll position in the transcript, `O` sets out-point — direct borrow from Avid/Premiere convention, not invented here, because it's already muscle memory for anyone who's touched an NLE.
- Marked clips appear in a running list on the right as you go — you never leave this screen to see what you've marked.
- One button renders everything you've marked, in a batch — never one clip at a time.

### 5.3 Quick clip — polish & export

Opens after a batch render, one clip at a time in a lightweight stepper (not a full NLE). Client's caption style and branding are pre-applied — you're checking, not configuring.

```
┌─ tally rail
│  Clip 2 of 5                                    ◂ prev   next ▸
│ ┌───────────────────────┐   Caption text (auto-filled, editable)
│ │                       │   ┌───────────────────────────────┐
│ │      [preview]        │   │ "...whole model was wrong."    │
│ │                       │   └───────────────────────────────┘
│ └───────────────────────┘
│  ▮▮▮▯▯▯▯▯▯▯  trim handles    [Looks good →]   [Open full editor]
```

- Default view shows only: preview, trim handles, caption text, one confirm action. This is the "Quick Clip" mode described in the technical PRD — everything else FreeCut can do sits behind "Open full editor," not in front of you by default.
- "Looks good" advances to the next clip in the batch immediately — no save dialog, no confirmation modal.

### 5.4 Package & deliver

The last step, and it should barely need a screen — mostly a confirmation of what's about to be sent.

```
┌─ tally rail
│  Acme Podcast — Ep. 42 — 5 clips ready
│  acme_ep42_clip1.mp4
│  acme_ep42_clip2.mp4
│  ...
│                                    [Package & mark delivered]
```

- One action. Files are already named and organized by the time you see this screen — naming happens automatically at render time, not here.

---

## 6. Interaction principles

- **No modal dialogs in the daily flow.** Confirmations, if truly needed, are inline (a button that briefly becomes "Confirm?" on second click) — never a popup that blocks the screen behind it.
- **Autosave everything.** Clip marks, caption edits, trim points — saved as you go. Never a "you have unsaved changes" moment.
- **Batch is the default, single is the exception.** Any action that could apply to multiple clips (render, export, deliver) should default to "all of them," with per-clip override available, not the reverse.
- **Hotkeys for anything you'll do more than a few times a day**, always visible in a small persistent legend, never hidden behind a "press ? for shortcuts" discovery step.

| Key | Action |
|---|---|
| `I` | Mark clip in-point |
| `O` | Mark clip out-point |
| `Enter` | Confirm current clip, advance |
| `←` `→` | Previous / next clip in batch |
| `Space` | Play/pause preview |

---

## 7. What this explicitly forbids

Carried over from the technical audit — the design language must not reopen the door to the bloat that was cut:

- No effects, masks, keyframe, or color-grading panels visible by default anywhere in the daily flow.
- No multi-track timeline UI for a single clip.
- No settings you must configure per-episode — if it's a setting, it belongs on the client's saved preset, set once.
- No dashboard/status-chain visualizations that exist to look complete rather than to tell you what to do next.
- No onboarding, tooltips-required interactions, or empty states that need explanatory copy — this tool has one user who already knows what it does.

---

## 8. Before shipping any UI change

Ask, in order:
1. Does this reduce clicks or time-on-task for a routine episode?
2. Can this live on a saved preset instead of being a decision I make every time?
3. Could I explain what to do here without reading anything, just from color and position?

If a change fails all three, it doesn't belong in this tool yet — however nice it looks.

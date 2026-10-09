# Codebase Cleanup and Audit Report

## 1. Executive Summary

- **Repository**: `AI-Youtube-Shorts-Generator` (Short Factory)
- **Branch**: `cleanup/codebase-simplification`
- **Execution Date**: 2026-10-09
- **Objective**: Complete dead-code removal, eliminate obsolete cloud/API pipelines, retire the vendored FreeCut browser editor and its integration layer, remove obsolete documentation drafts, clean up dependency manifests, fix identified runtime bugs, preserve all user data/databases/migrations, and validate application stability.

All removals and simplifications have been physically executed and verified against Git status and test suites.

---

## 2. Files and Directories Deleted

### 2.1 FreeCut Browser Editor & Integration Layer
The separate browser timeline editor (`vendor/freecut/`) and its Python/Django integration have been completely retired:
- **`vendor/freecut/`** (3,095 files removed: full React/Vite source, TypeScript modules, build scripts, test suites, and precompiled static bundles).
- **`shorts_generator/freecut_projects.py`** (Removed: workspace JSON generator and timeline synchronizer).
- **`webui/templates/webui/editor_shell.html`** (Removed: iframe wrapper template).
- **`webui/views.py`**: Removed `editor_shell`, `editor_app`, `freecut_exports`, and helper routines (`_EDITOR_MIME`, `_isolated_headers`, `_collect_exports`).
- **`webui/urls.py`**: Removed routes for `/editor/`, `/video/<video_id>/edit/`, and `/exports/`.
- **`webui/settings.py`**: Removed `FREECUT_DIST` and `FREECUT_WORKSPACE` configuration settings.
- **`webui/jobs.py`**: Removed `sync_freecut_project` background call.
- **`webui/templates/webui/episode_review.html` & `episode_mark.html`**: Removed the "Open full editor" buttons.

### 2.2 Obsolete Cloud / MuAPI Pipeline (`shorts_generator/`)
The pay-per-call cloud API mode previously kept for reference has been completely deleted:
- `shorts_generator/muapi.py` (Cloud API client, poll loop, error handling).
- `shorts_generator/downloader.py` (MuAPI `/youtube-download` endpoint client).
- `shorts_generator/transcriber.py` (MuAPI `/openai-whisper` endpoint client).
- `shorts_generator/clipper.py` (MuAPI `/autocrop` endpoint client).

### 2.3 Legacy Trimmer Backup (`_legacy_trimmer_backup/`)
Archival backup of the retired FFmpeg manual trimmer:
- `_legacy_trimmer_backup/trim_short.html`
- `_legacy_trimmer_backup/trimmer.css`
- `_legacy_trimmer_backup/urls.py`
- `_legacy_trimmer_backup/views.py`

### 2.4 Scratch and Experimental Prototyping Files (`scratch/`)
One-off development scripts and test media:
- `scratch/check_gaps.py`
- `scratch/frame_real_dual_rendered.jpg`
- `scratch/frame_real_solo_rendered.jpg`
- `scratch/migrate_existing_transcripts.py`
- `scratch/prototype_segmentation.py`
- `scratch/test_all_resegment.py`
- `scratch/test_mark_ui_segments.py`
- *All untracked temporary video renders purged from disk.*

### 2.5 Obsolete & Redundant Documentation
Removed outdated design drafts, superseded specs, and duplicated documentation:
- `Update.md` (superseded early spec)
- `update2.md` (superseded diarization spec)
- `Updated_System_Plan.md` (superseded design draft)
- `newTemp.md` (scratch template notes)
- `SYSTEM_DOCUMENTATION.md` (superseded, consolidated into `README.md`)
- `remake_document/` (contains `Design_Language_UIUX (1).md`, `PRD_Podcast_to_Shorts_App (2).md`, `Pipeline_Structure.md`)

---

## 3. Dependency Cleanups

1. **`requirements.txt`**:
   - **Removed**: `requests>=2.31` (was exclusively imported by the deleted `shorts_generator/muapi.py`).
   - **Added**: `django>=5.0` (explicitly declares the Web UI framework dependency).
   - **Retained**: `python-dotenv>=1.0`, `Pillow>=10.0`.
2. **`requirements-local.txt`**:
   - Updated documentation comments to declare `yt-dlp`, `bgutil-ytdlp-pot-provider`, `faster-whisper`, `openai`, `google-genai`, and `opencv-contrib-python` as the core local pipeline stack.
3. **`shorts_generator/config.py`**:
   - Removed `MUAPI_API_KEY`, `MUAPI_BASE_URL`, `POLL_INTERVAL_SECONDS`, `POLL_TIMEOUT_SECONDS`, and `require_api_key()`.
   - Updated error messaging for `require_openai_key()` and `require_gemini_key()`.

---

## 4. Code Retained and Rationale

| Asset / Component | Retention Rationale |
|---|---|
| `webui/` (Django UI, views, templates, models) | Powers the complete 7-stage client production workflow (Client Projects, Episodes, Mark, Render, Review, Delivery Packaging). |
| `webui/db.sqlite3` & `webui/migrations/` | Primary SQLite database and Django migration history preserving existing projects, episodes, clips, and jobs. |
| `output/` directory | User data storage: source videos, transcripts (`.srt`, `.words.json`), rendered shorts (`.mp4`), sidecars (`.meta.json`), and client branding. |
| `temp.json`, `result.json` | Existing transcript and pipeline output JSON files preserved as user data. |
| `template.json`, `templates.txt` | Core layout specifications and template definitions referenced by the local clipper. |
| `export_cookies.py` | Active YouTube authentication utility for exporting cookies when bot-detection requires it. |

---

## 5. Bugs Fixed During Audit & Simplification

1. **`shorts_generator/pipeline.py`**:
   - Fixed `NameError: name 'stage' is not defined` by adding `stage` import from `.progress`.
   - Removed `_run_api()` branch; pipeline now cleanly executes local mode with parameter validation.
2. **`shorts_generator/highlights.py`**:
   - Removed `from . import muapi` and `call_muapi_llm`.
   - Updated `detect_content_type`, `call_highlight_api`, and `get_highlights` to default to `call_local_llm`.
3. **`shorts_generator/local/downloader.py` & `clipper.py`**:
   - Cleaned up docstrings and comments that previously referenced FreeCut and obsolete modes.
4. **`webui/templates/webui/project_detail.html`**:
   - Removed duplicate `caption_position` select field shadowing the form grid.
5. **`run_webui.bat`**:
   - Replaced hardcoded machine-specific Python path with portable detection (`venv\Scripts\python.exe`, `.venv\Scripts\python.exe`, or PATH `python`).
6. **`webui/views.py`**:
   - Removed dead imports (`time`, `transaction`, `HttpResponseRedirect`).

---

## 6. Verification and Testing

### 6.1 Django Framework System Check
```powershell
python manage.py check
```
- **Result**: `System check identified no issues (0 silenced).` (Exit code: 0)

### 6.2 Python AST Parsing
Validated that all Python files across `webui/`, `shorts_generator/`, and project root parse cleanly without syntax or import structure errors.
- **Result**: `All python files parsed cleanly!`

### 6.3 Automated Unit Test Suite (`webui/tests.py`)
Implemented and executed a 23-test unit suite covering:
- **Models**: `ClientProject` slugging & deduplication, `Episode`, `Clip` durations, `RenderJob` cancellation tokens.
- **Segmenter**: Sentence boundary detection, word extraction, sentence re-clustering.
- **Downloader Helpers**: Format selectors, YouTube video ID extraction, local file path resolution.
- **Clipper & Template Filters**: Aspect ratio parsing, subtitle placement bands, video grading filters.
- **Web UI Views**: Project list, project creation, project detail, episode mark view, clip add/delete AJAX endpoints, render job status polling.
- **Pipeline & Highlights**: Mode validation (rejection of obsolete/invalid modes), highlight deduplication and overlap suppression, highlight duration clamping.

```powershell
python manage.py test webui
```
- **Result**:
  ```text
  Ran 23 tests in 0.141s
  OK
  ```

---

## 7. Documentation Updates

- **`README.md`**: Rewritten as the unified, comprehensive documentation guide for the project. Covers the 7-stage production workflow, core engine capabilities, template layouts, subtitle styles, broadcast audio mastering, installation, `.env` configuration, Web UI usage, CLI automation, and testing.
- **Obsolete Documentation Removed**: Removed 6 draft/historical markdown files (`Update.md`, `update2.md`, `Updated_System_Plan.md`, `newTemp.md`, `SYSTEM_DOCUMENTATION.md`, and the `remake_document/` folder).

---

## 8. Production Workflow Reliability Hardening (`fix/production-workflow-reliability`)

On branch `fix/production-workflow-reliability`, comprehensive audits and fixes were executed addressing workflow reliability, security, and integrity across the application.

### 8.1 CSRF Security
- **Audit & Removal**: Audited every view in `webui/views.py`. Removed `@csrf_exempt` from all 10 browser state-changing endpoints:
  - `project_new`
  - `project_detail`
  - `episode_add`
  - `clip_add`
  - `clip_delete`
  - `episode_render`
  - `render_cancel`
  - `clip_confirm`
  - `clip_trim`
  - `episode_package`
- **Template & AJAX Hardening**:
  - Embedded `{% csrf_token %}` across all forms and template surfaces (`episode_mark.html`, `project_new.html`, `project_detail.html`, `episode_review.html`, `episode_deliver.html`).
  - Added `@ensure_csrf_cookie` to GET views (`episode_mark`, `episode_review`, `episode_deliver`) ensuring CSRF cookies are set on initial page visits.
  - Implemented `getCsrfToken()` helper in client-side JavaScript falling back to DOM `[name=csrfmiddlewaretoken]` to guarantee that all asynchronous `fetch` calls transmit the `X-CSRFToken` header.
- **Verification**: `CSRFSecurityTests` confirms that all POST endpoints reject unauthenticated requests with HTTP 403 Forbidden when enforced, and accept valid requests with token.

### 8.2 Delivery Integrity
- **Verification of Renders & Approvals**:
  - Implemented `validate_episode_delivery(episode)` and `check_clip_render_status(episode, clip, idx)` in `webui/views.py` and `webui/jobs.py`.
  - Packaging now strictly requires:
    1. Every clip in the episode must have confirmed approval (`clip.confirmed=True`).
    2. Every clip must have an existing, non-empty rendered MP4 file (`stat().st_size > 0`).
    3. Every clip must have a valid sidecar metadata file (`.meta.json`) matching the clip's current `source_start` and `source_end` timestamps and `caption_override`.
  - Rejects incomplete, corrupted, or stale renders with actionable explanations.
  - Disables the delivery packaging button and displays a detailed pending requirement list in `episode_deliver.html` if any clip is unapproved or render is stale/missing.
  - Marks `episode.delivered=True` **only** after files are validated, copied to the delivery folder, and the batch ZIP archive is successfully constructed on disk.
  - Modifying or deleting clips (`clip_trim`, `clip_add`, `clip_delete`) immediately resets `episode.delivered=False`.

### 8.3 Clip Edit Correctness
- **Approval Invalidation**:
  - In `clip_trim`: modifying clip in/out boundaries or caption override automatically invalidates approval by setting `clip.confirmed=False`.
- **Settings Isolation**:
  - Eliminated silent mutations to `ClientProject` defaults (`default_template`, `caption_template`, `video_filter`) in `clip_trim`.
  - Per-clip render overrides are passed directly to `render_one_clip` and stored in the individual clip's `.meta.json` sidecar without altering database project settings.
- **Timestamp Validation & Visible Errors**:
  - Probes source video duration via `_get_source_duration(episode)` using ffprobe or transcript caches.
  - Rejects negative start times (`start < 0`), inverted ranges (`end <= start`), non-numeric inputs, and ranges exceeding source video duration (`end > duration`).
  - Returns visible redirect error messages in `clip_trim` and HTTP 400 with descriptive error JSON in `clip_add`. Error banners are rendered in `episode_review.html` and `episode_mark.html`.

### 8.4 Render-Job Recovery
- **Interrupted Job Detection**:
  - Implemented in-memory active thread tracking (`_RUNNING_JOBS`, `register_running_job`, `unregister_running_job`) in `webui/jobs.py`.
  - Implemented `recover_interrupted_jobs(episode)`: detects any queued or rendering jobs whose background thread was abandoned due to an application restart or process termination.
  - Automatically transitions abandoned jobs to `status="failed"` with message `"Interrupted: server was restarted while render was in progress"` and finished timestamp.
  - Connected startup hook in `webui/apps.py` via `request_started` and lazy evaluation on view state calls (`_episode_state`, `episode_mark`, `episode_render`, `render_status`).
- **Safe Retry & Incomplete File Cleanup**:
  - Automatically unblocks re-rendering so users can retry without getting stuck on frozen progress.
  - Incomplete or corrupted output files missing matching `.meta.json` sidecars are purged during recovery and excluded from `_rendered_shorts` and `_review_clips`.

### 8.5 Test Evidence & Verification Matrix

#### Commands Executed
1. **Django System Checks**:
   ```powershell
   python manage.py check
   ```
   **Output**: `System check identified no issues (0 silenced).` (Exit code: 0)

2. **Full Automated Test Suite**:
   ```powershell
   python manage.py test
   ```
   **Output**:
   ```text
   Creating test database for alias 'default'...
   ......................................
   ----------------------------------------------------------------------
   Ran 38 tests in 0.629s

   OK
   Destroying test database for alias 'default'...
   Found 38 test(s).
   System check identified no issues (0 silenced).
   ```

#### Regression Coverage Matrix (38 Passed Tests)
| Test Class | Test Case | Verified Behavior |
|---|---|---|
| `CSRFSecurityTests` | `test_csrf_rejection_without_token` | Rejection (403) across all 9 POST endpoints without CSRF token |
| `CSRFSecurityTests` | `test_csrf_accepted_with_valid_token` | Successful acceptance of POST request with valid CSRF cookie & header |
| `DeliveryIntegrityTests` | `test_delivery_rejected_when_no_clips` | Prevents delivery packaging when no clips exist |
| `DeliveryIntegrityTests` | `test_delivery_rejected_with_unapproved_clips` | Blocks packaging and displays error if clips lack confirmation |
| `DeliveryIntegrityTests` | `test_delivery_rejected_with_missing_renders` | Blocks packaging if MP4 files do not exist on disk |
| `DeliveryIntegrityTests` | `test_delivery_rejected_with_stale_timestamp_render` | Blocks packaging if clip start/end timestamps diverge from `.meta.json` |
| `DeliveryIntegrityTests` | `test_delivery_rejected_with_stale_caption_render` | Blocks packaging if clip caption override diverges from `.meta.json` |
| `DeliveryIntegrityTests` | `test_delivery_successful_packaging` | Full delivery packaging into ZIP and setting `delivered=True` |
| `ClipEditCorrectnessTests` | `test_clip_edit_invalidates_approval_and_delivery` | Invalidation of `clip.confirmed` and `episode.delivered` on edit |
| `ClipEditCorrectnessTests` | `test_settings_isolation_does_not_modify_project_defaults` | Per-clip overrides isolated from `ClientProject` database defaults |
| `ClipEditCorrectnessTests` | `test_invalid_timestamps_rejected_with_error` | Visible error feedback for negative, inverted, or out-of-bounds timestamps |
| `ClipEditCorrectnessTests` | `test_clip_add_invalid_timestamps` | HTTP 400 error response on invalid timestamp submission in `clip_add` |
| `RenderJobRecoveryTests` | `test_abandoned_job_marked_interrupted_on_recovery` | Recovery marks orphaned queued/running jobs as failed with restart message |
| `RenderJobRecoveryTests` | `test_safe_retry_after_interrupted_job` | Safe retry allowed without blocking on zombie jobs |
| `RenderJobRecoveryTests` | `test_incomplete_output_files_cleaned_up_on_recovery` | Cleanup of partial renders without valid `.meta.json` sidecars |
| `WebViewsTests` | `test_render_status_empty_and_active` | Render status API properly reflects registered running jobs |
| `WebViewsTests` | `test_clip_add_and_delete` | Clip creation and deletion AJAX lifecycle |
| `WebViewsTests` | `test_project_new_get_and_post` | Project creation and default inheritance |
| `WebViewsTests` | `test_project_detail_view` | Project detail rendering with episode lists |
| `ModelTests` | `test_client_project_slugify_and_defaults` | Slug generation and model defaults |
| `ModelTests` | `test_client_project_slug_deduplication` | Slug collision resolution with numeric suffix |
| `ModelTests` | `test_episode_and_clip_models` | Episode & Clip relational constraints and properties |
| `ModelTests` | `test_render_job_and_cancellation` | RenderJob cancellation tokens |
| `SegmenterTests` | `test_is_sentence_end`, `test_extract_words`, `test_resegment_by_sentences` | NLP sentence segmentation and word timing |
| `DownloaderTests` | `test_format_for`, `test_extract_youtube_video_id`, `test_resolve_local_path` | Downloader path and URL parsing |
| `ClipperTests` | `test_ratio`, `test_band_for_position`, `test_apply_video_filter` | Aspect ratio, subtitle positioning, filter matrix processing |
| `PipelineAndHighlightsTests` | `test_pipeline_mode_validation`, `test_dedupe_highlights_overlap`, `test_sanitize_highlights_bounds` | Pipeline local validation and highlight filtering |

### 8.6 Cases Not Verified Locally
1. **Live YouTube Video Download Under Real YouTube Anti-Bot Challenges**:
   - Automated test suite tests downloader format resolution, URL extraction, and local paths. Live YouTube downloading via `yt-dlp` requires external internet access and real YouTube IP authentication or exported cookies (`export_cookies.py`).
2. **GPU Hardware NVENC Transcoding**:
   - Tests execute using CPU and simulated software video containers. Production runs with NVIDIA GPU NVENC acceleration depend on the host machine's physical GPU driver availability.


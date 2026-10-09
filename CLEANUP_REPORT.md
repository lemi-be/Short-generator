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

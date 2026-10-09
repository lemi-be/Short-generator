"""Background render worker for the fast-path pipeline.

`run_render_job` runs a whole episode's batch in a background thread so the
UI can poll progress (amber tally rail). Each clip is cut + reframed to 9:16
with the client's saved caption style and branding burned in.

Thread safety: Django DB connections are per-thread, so the worker closes its
connection on entry/exit (sqlite + runserver handle this fine).
"""
import json
import os
import sys
import traceback
from pathlib import Path

from django.utils import timezone


def _short_name(episode, idx: int) -> str:
    return f"{episode.project.slug}_{episode.pk:04d}_clip{idx:02d}.mp4"


def _load_transcript(episode):
    """Best-effort transcript with word timestamps from the .srt/.words.json cache."""
    out = Path(episode.source_file).parent if episode.source_file else None
    srt = Path(episode.source_file).with_suffix(".srt") if episode.source_file else None
    if srt is None or not srt.exists():
        return None
    from shorts_generator.local.transcriber import _load_srt_cache
    return _load_srt_cache(srt)


def _caption_style(project):
    return {
        "caption_template": getattr(project, "caption_template", "hormozi_pop"),
        "font": project.caption_font,
        "color": project.caption_color,
        "position": project.caption_position,
        "zoom_punch": getattr(project, "zoom_punch", True),
        "master_audio": getattr(project, "master_audio", True),
        "hook_card": getattr(project, "hook_card", True),
        "podcast_solo_switch": getattr(project, "podcast_solo_switch", True),
        "video_filter": getattr(project, "video_filter", "vivid_pop"),
    }


def _branding(project):
    logo = None
    if project.brand_logo:
        p = Path(project.brand_logo)
        if p.exists():
            logo = str(p)
    return {"logo": logo, "lower_third": project.brand_lower_third}


_CANCELLED_JOBS = set()
_RUNNING_JOBS = set()


def cancel_job_in_memory(job_id: int) -> None:
    _CANCELLED_JOBS.add(job_id)


def is_job_cancelled(job_id: int) -> bool:
    return job_id in _CANCELLED_JOBS


def register_running_job(job_id: int) -> None:
    _RUNNING_JOBS.add(job_id)


def unregister_running_job(job_id: int) -> None:
    _RUNNING_JOBS.discard(job_id)


def is_job_running(job_id: int) -> bool:
    return job_id in _RUNNING_JOBS


def check_clip_render_status(episode, clip, idx: int) -> tuple:
    """Check if rendered MP4 file exists, is non-empty, and matches clip timestamps and settings."""
    from django.conf import settings
    out_dir = Path(settings.OUTPUT_DIR)
    name = _short_name(episode, idx)
    mp4_path = out_dir / name
    if not mp4_path.exists():
        return False, f"Clip {idx} rendered MP4 ({name}) is missing."
    if not mp4_path.is_file() or mp4_path.stat().st_size == 0:
        return False, f"Clip {idx} rendered MP4 ({name}) is empty (0 bytes)."

    meta_path = out_dir / f"{mp4_path.stem}.meta.json"
    if not meta_path.exists():
        meta_path = out_dir / f"{mp4_path.name}.meta.json"
    if not meta_path.exists():
        return False, f"Clip {idx} render metadata sidecar is missing."

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"Clip {idx} render metadata is corrupted ({exc})."

    if meta.get("status") not in (None, "complete"):
        return False, f"Clip {idx} render was not completed."

    if meta.get("clip_id") and meta.get("clip_id") != clip.pk:
        return False, f"Clip {idx} render metadata does not belong to this clip."

    meta_start = float(meta.get("source_start", -999))
    meta_end = float(meta.get("source_end", -999))
    if abs(meta_start - clip.start_time) > 0.05 or abs(meta_end - clip.end_time) > 0.05:
        return (
            False,
            f"Clip {idx} render is stale: render timestamps ({meta_start:.1f}s - {meta_end:.1f}s) "
            f"do not match current clip timestamps ({clip.start_time:.1f}s - {clip.end_time:.1f}s).",
        )

    meta_caption = (meta.get("caption_override") or "").strip()
    clip_caption = (clip.caption_override or "").strip()
    if meta_caption != clip_caption:
        return (
            False,
            f"Clip {idx} render is stale: caption override was changed after rendering.",
        )

    return True, "OK"


def is_valid_clip_render(episode, clip, idx: int) -> bool:
    valid, _ = check_clip_render_status(episode, clip, idx)
    return valid


def recover_interrupted_jobs(episode=None) -> list:
    """Find any queued or rendering jobs whose in-memory worker thread is not running
    (e.g. after server restart or crash), mark them failed, and clean up incomplete renders."""
    from .models import RenderJob
    from django.conf import settings

    qs = RenderJob.objects.filter(
        status__in=[RenderJob.STATUS_QUEUED, RenderJob.STATUS_RENDERING]
    )
    if episode is not None:
        qs = qs.filter(episode=episode)

    interrupted = []
    for job in qs:
        if not is_job_running(job.pk):
            job.status = RenderJob.STATUS_FAILED
            job.message = "Interrupted: server was restarted while render was in progress"
            job.error = "Render job was interrupted by server restart or process termination. Safe to retry."
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "message", "error", "finished_at"])
            interrupted.append(job)

            # Cleanup incomplete renders for this episode:
            try:
                ep = job.episode
                clips = sorted(ep.clips.all(), key=lambda c: c.start_time)
                out_dir = Path(settings.OUTPUT_DIR)
                for i, clip in enumerate(clips, 1):
                    mp4_path = out_dir / _short_name(ep, i)
                    if mp4_path.exists() and not is_valid_clip_render(ep, clip, i):
                        try:
                            mp4_path.unlink()
                        except OSError:
                            pass
                        meta_path = out_dir / f"{mp4_path.stem}.meta.json"
                        if meta_path.exists():
                            try:
                                meta_path.unlink()
                            except OSError:
                                pass
            except Exception:
                pass

    return interrupted


_RECOVERY_DONE = False


def ensure_startup_recovery():
    global _RECOVERY_DONE
    if not _RECOVERY_DONE:
        _RECOVERY_DONE = True
        try:
            recover_interrupted_jobs()
        except Exception:
            pass


class JobCancellationToken:
    """Progress tracker and cancellation token passed to video clippers."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        self.total = 0.0
        self.current = 0.0

    def set_total(self, total: float) -> None:
        self.total = float(total) if total else 0.0

    def update(self, current: float) -> None:
        self.current = float(current)

    def finish(self, message: str = None) -> None:
        pass

    def fail(self, error: str = None) -> None:
        pass

    @property
    def is_cancelled(self) -> bool:
        return self.check_cancelled()

    def check_cancelled(self) -> bool:
        if is_job_cancelled(self.job_id):
            return True
        try:
            from .models import RenderJob
            job = RenderJob.objects.filter(pk=self.job_id).only("status").first()
            if job and job.status == RenderJob.STATUS_CANCELLED:
                cancel_job_in_memory(self.job_id)
                return True
        except Exception:
            pass
        return False


def render_one_clip(
    episode,
    clip,
    idx: int,
    out_path: Path,
    progress=None,
    template: str = None,
    caption_template: str = None,
    video_filter: str = None,
) -> None:
    """Render a single clip. Shared by the batch job and the trim re-render."""
    from shorts_generator.local.clipper import _clip_local_segments, crop_clip_local

    source = Path(episode.source_file)
    if not source.exists():
        raise RuntimeError(f"source missing: {source}")

    transcript = _load_transcript(episode)
    segments = (
        _clip_local_segments(transcript, clip.start_time, clip.end_time)
        if transcript and transcript.get("segments")
        else None
    )

    clip_title = (clip.caption_override or episode.title or "").strip() or None
    chosen_template = template or episode.project.default_template or "full_bleed_solo"
    style = _caption_style(episode.project)
    if caption_template:
        style["caption_template"] = caption_template
    if video_filter:
        style["video_filter"] = video_filter

    crop_clip_local(
        str(source),
        clip.start_time,
        clip.end_time,
        str(out_path),
        template=chosen_template,
        progress=progress,
        text=None,
        title=clip_title,
        segments=segments,
        burn_captions=True,
        caption_style=style,
        branding=_branding(episode.project),
    )

    meta_content = json.dumps({
        "project_id": episode.project_id,
        "episode_id": episode.pk,
        "clip_id": clip.pk,
        "index": idx,
        "source_start": clip.start_time,
        "source_end": clip.end_time,
        "caption_override": clip.caption_override,
        "template": chosen_template,
        "caption_template": style.get("caption_template"),
        "video_filter": style.get("video_filter"),
        "status": "complete",
        "rendered_at": timezone.now().isoformat(),
    })
    (out_path.parent / f"{out_path.stem}.meta.json").write_text(meta_content, encoding="utf-8")
    out_path.with_suffix(".mp4.meta.json").write_text(meta_content, encoding="utf-8")


def run_render_job(job_id: int) -> None:
    from django.db import close_old_connections
    from .models import RenderJob

    close_old_connections()
    register_running_job(job_id)
    job = RenderJob.objects.select_related("episode", "episode__project").filter(pk=job_id).first()
    if job is None:
        unregister_running_job(job_id)
        return
    try:
        episode = job.episode
        job.status = RenderJob.STATUS_RENDERING
        job.message = "starting batch render"
        job.save(update_fields=["status", "message"])

        clips = sorted(episode.clips.all(), key=lambda c: c.start_time)
        total = len(clips)
        if total == 0:
            raise RuntimeError("No clips marked for this episode.")

        out_dir = Path(episode.source_file).parent if episode.source_file else Path("output")
        out_dir = out_dir.resolve()

        for i, clip in enumerate(clips, 1):
            token = JobCancellationToken(job_id)
            if token.check_cancelled():
                raise InterruptedError("Render cancelled by user.")

            job.refresh_from_db()
            if job.status == RenderJob.STATUS_CANCELLED:
                cancel_job_in_memory(job_id)
                raise InterruptedError("Render cancelled by user.")

            job.message = f"rendering clip {i}/{total}"
            job.progress = int((i - 1) / total * 100)
            job.save(update_fields=["message", "progress"])

            clip_target = out_dir / _short_name(episode, i)
            try:
                render_one_clip(episode, clip, i, clip_target, progress=token)
            except InterruptedError:
                if clip_target.exists():
                    try:
                        os.remove(clip_target)
                    except Exception:
                        pass
                raise

        job.status = RenderJob.STATUS_DONE
        job.progress = 100
        job.message = "batch complete"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "progress", "message", "finished_at"])
    except InterruptedError:
        job.status = RenderJob.STATUS_CANCELLED
        job.message = "Render cancelled by user"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "finished_at"])
        _CANCELLED_JOBS.discard(job_id)
        print(f"[render-job {job_id}] Cancelled by user.")
    except Exception:
        job.status = RenderJob.STATUS_FAILED
        job.error = traceback.format_exc()
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        _CANCELLED_JOBS.discard(job_id)
        print(f"[render-job {job_id}] FAILED:\n{job.error}", file=sys.stderr)
    finally:
        _CANCELLED_JOBS.discard(job_id)
        unregister_running_job(job_id)
        close_old_connections()
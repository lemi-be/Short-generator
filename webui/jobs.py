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


def cancel_job_in_memory(job_id: int) -> None:
    _CANCELLED_JOBS.add(job_id)


def is_job_cancelled(job_id: int) -> bool:
    return job_id in _CANCELLED_JOBS


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


def render_one_clip(episode, clip, idx: int, out_path: Path, progress=None) -> None:
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
    crop_clip_local(
        str(source),
        clip.start_time,
        clip.end_time,
        str(out_path),
        template=episode.project.default_template or "full_bleed_solo",
        progress=progress,
        text=None,
        title=clip_title,
        segments=segments,
        burn_captions=True,
        caption_style=_caption_style(episode.project),
        branding=_branding(episode.project),
    )

    meta = out_path.with_suffix(".mp4.meta.json")
    meta.write_text(json.dumps({
        "project_id": episode.project_id,
        "episode_id": episode.pk,
        "clip_id": clip.pk,
        "index": idx,
        "source_start": clip.start_time,
        "source_end": clip.end_time,
        "caption_override": clip.caption_override,
    }), encoding="utf-8")


def run_render_job(job_id: int) -> None:
    from django.db import close_old_connections
    from .models import RenderJob

    close_old_connections()
    job = RenderJob.objects.select_related("episode", "episode__project").filter(pk=job_id).first()
    if job is None:
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

        # Best-effort: register the batch in FreeCut's workspace for the
        # advanced editor path.
        try:
            from shorts_generator.freecut_projects import sync_freecut_project
            short_paths = [out_dir / _short_name(episode, i) for i in range(1, total + 1)]
            sync_freecut_project(
                out_dir,
                episode.video_id,
                episode.title or episode.video_id,
                [p for p in short_paths if p.exists()],
                transcript=_load_transcript(episode),
            )
        except Exception:
            pass  # never break delivery because the editor sync failed

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
        close_old_connections()
"""Background render worker for the fast-path pipeline.

`run_render_job` runs a whole episode's batch in a background thread so the
UI can poll progress (amber tally rail). Each clip is cut + reframed to 9:16
with the client's saved caption style and branding burned in.

Thread safety: Django DB connections are per-thread, so the worker closes its
connection on entry/exit (sqlite + runserver handle this fine).
"""
import json
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
        "font": project.caption_font,
        "color": project.caption_color,
        "position": project.caption_position,
    }


def _branding(project):
    logo = None
    if project.brand_logo:
        p = Path(project.brand_logo)
        if p.exists():
            logo = str(p)
    return {"logo": logo, "lower_third": project.brand_lower_third}


def render_one_clip(episode, clip, idx: int, out_path: Path) -> None:
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

    crop_clip_local(
        str(source),
        clip.start_time,
        clip.end_time,
        str(out_path),
        template=episode.project.default_template or "stage_solo_speaker",
        text=None,
        title=None,
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
            job.message = f"rendering clip {i}/{total}"
            job.progress = int((i - 1) / total * 100)
            job.save(update_fields=["message", "progress"])
            render_one_clip(episode, clip, i, out_dir / _short_name(episode, i))

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
    except Exception:
        job.status = RenderJob.STATUS_FAILED
        job.error = traceback.format_exc()
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "finished_at"])
        print(f"[render-job {job_id}] FAILED:\n{job.error}", file=sys.stderr)
    finally:
        close_old_connections()
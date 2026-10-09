import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotFound, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from urllib.parse import quote

from .models import ClientProject, Clip, Episode, RenderJob

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Small formatting / fs helpers ──────────────────────────────────────

def _fmt_ts(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.strip())
    segments = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            int(lines[0])
        except ValueError:
            continue
        m = re.match(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})",
            lines[1],
        )
        if not m:
            continue
        start = (
            int(m.group(1)) * 3600
            + int(m.group(2)) * 60
            + int(m.group(3))
            + int(m.group(4)) / 1000
        )
        end = (
            int(m.group(5)) * 3600
            + int(m.group(6)) * 60
            + int(m.group(7))
            + int(m.group(8)) / 1000
        )
        segments.append(
            {
                "index": int(lines[0]),
                "start": start,
                "end": end,
                "text": " ".join(lines[2:]),
            }
        )
    return segments


def _ffprobe(path: Path, entry: str = "format=duration"):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entry, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return r.stdout.strip() if r.returncode == 0 else "0"


def _read_video_title(video_id: str) -> str:
    title_file = Path(settings.OUTPUT_DIR) / f"source_{video_id}.title"
    try:
        return title_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _transcript_for(video_id: str):
    srt_path = Path(settings.OUTPUT_DIR) / f"source_{video_id}.srt"
    if not srt_path.exists():
        return None
    from shorts_generator.local.transcriber import _load_srt_cache
    cached = _load_srt_cache(srt_path)
    return cached.get("segments") or _parse_srt(srt_path)


def _source_path(video_id: str) -> Path:
    return Path(settings.OUTPUT_DIR) / f"source_{video_id}.mp4"


def _short_name(episode: Episode, idx: int) -> str:
    return f"{episode.project.slug}_{episode.pk:04d}_clip{idx:02d}.mp4"


def _rendered_shorts(episode: Episode):
    out = Path(settings.OUTPUT_DIR)
    return sorted(out.glob(f"{episode.project.slug}_{episode.pk:04d}_clip*.mp4"))


def _caption_style(project: ClientProject) -> dict:
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


def _branding(project: ClientProject) -> dict:
    logo = None
    if project.brand_logo:
        candidate = Path(settings.OUTPUT_DIR) / "branding" / project.slug / "branding.png"
        if candidate.exists():
            logo = str(candidate)
    return {
        "logo": logo,
        "lower_third": project.brand_lower_third,
    }


# ── Tally state ────────────────────────────────────────────────────────

def _episode_state(episode: Episode):
    """Return (color, message, counts) where color in {red, amber, green, off}."""
    source = _source_path(episode.video_id)
    srt = Path(settings.OUTPUT_DIR) / f"source_{episode.video_id}.srt"
    clips = list(episode.clips.all())
    active = episode.render_jobs.exclude(
        status__in=[RenderJob.STATUS_DONE, RenderJob.STATUS_FAILED, RenderJob.STATUS_CANCELLED]
    ).first()
    shorts = _rendered_shorts(episode)

    if active:
        return "amber", f"rendering {active.progress}%", {"rendering": True}
    if not source.exists():
        return "off", "no source", {}
    if not srt.exists():
        return "red", "not transcribed", {}
    if not clips:
        return "red", "no clips marked", {"unmarked": 0, "clips": 0}
    unconfirmed = sum(1 for c in clips if not c.confirmed)
    if unconfirmed:
        return "red", f"{unconfirmed} clip{'s' if unconfirmed != 1 else ''} to review", {
            "unmarked": 0,
            "clips": len(clips),
            "unconfirmed": unconfirmed,
            "rendered": len(shorts),
        }
    if episode.delivered:
        return "green", "delivered", {"clips": len(clips), "rendered": len(shorts)}
    return "green", "ready to deliver", {"clips": len(clips), "rendered": len(shorts)}


def _project_state(project: ClientProject):
    episodes = list(project.episodes.all())
    if not episodes:
        return "off", "no episodes", {}
    order = {"red": 0, "amber": 1, "green": 2, "off": 3}
    states = [_episode_state(ep) for ep in episodes]
    worst = min(states, key=lambda s: order[s[0]])
    color = worst[0]
    message = f"{len(episodes)} episode{'s' if len(episodes) != 1 else ''}"
    counts = {
        "unmarked": sum(s[2].get("unconfirmed", 0) for s in states),
        "rendering": sum(1 for s in states if s[2].get("rendering")),
        "delivered": sum(1 for s in states if s[0] == "green"),
    }
    if color == "red":
        message = f"{counts['unmarked']} clip{'s' if counts['unmarked'] != 1 else ''} to review"
    elif color == "amber":
        message = f"{counts['rendering']} rendering"
    elif color == "green" and counts["delivered"] == len(episodes):
        message = "all clear"
    return color, message, counts


# ── Home ───────────────────────────────────────────────────────────────

def home(request):
    projects = []
    for p in ClientProject.objects.all():
        color, message, counts = _project_state(p)
        projects.append({"project": p, "color": color, "message": message, "counts": counts})
    order = {"red": 0, "amber": 1, "green": 2, "off": 3}
    projects.sort(key=lambda r: order[r["color"]])
    rail = "red"
    if projects:
        rail = projects[0]["color"]
    else:
        rail = "green"
    return render(request, "webui/home.html", {
        "projects": projects,
        "tally": rail,
        "error": request.GET.get("error", ""),
        "msg": request.GET.get("msg", ""),
    })


@csrf_exempt
def project_new(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(request, "webui/project_new.html", {
                "tally": "red",
                "error": "Client name is required.",
                "caption_templates": ClientProject.CAPTION_TEMPLATE_CHOICES,
                "fonts": ClientProject.CAPTION_FONT_CHOICES,
                "positions": ClientProject.CAPTION_POSITION_CHOICES,
                "video_filters": ClientProject.VIDEO_FILTER_CHOICES,
            })
        project = ClientProject.objects.create(
            name=name,
            caption_template=request.POST.get("caption_template", "hormozi_pop"),
            caption_font=request.POST.get("caption_font", "impact"),
            caption_color=request.POST.get("caption_color", "#FFEA00") or "#FFEA00",
            caption_position=request.POST.get("caption_position", "lower_third"),
            video_filter=request.POST.get("video_filter", "vivid_pop"),
            brand_lower_third=request.POST.get("brand_lower_third", "").strip(),
            default_template=request.POST.get("default_template", "full_bleed_solo"),
            zoom_punch="zoom_punch" in request.POST,
            master_audio="master_audio" in request.POST,
            hook_card="hook_card" in request.POST,
            podcast_solo_switch="podcast_solo_switch" in request.POST,
        )
        # Optional branding logo upload.
        logo = request.FILES.get("brand_logo")
        if logo:
            brand_dir = Path(settings.OUTPUT_DIR) / "branding" / project.slug
            brand_dir.mkdir(parents=True, exist_ok=True)
            dest = brand_dir / "branding.png"
            with open(dest, "wb") as f:
                for chunk in logo.chunks():
                    f.write(chunk)
            project.brand_logo = str(dest)
            project.save(update_fields=["brand_logo"])
        return redirect("project_detail", project_id=project.pk)
    return render(request, "webui/project_new.html", {
        "tally": "amber",
        "caption_templates": ClientProject.CAPTION_TEMPLATE_CHOICES,
        "fonts": ClientProject.CAPTION_FONT_CHOICES,
        "positions": ClientProject.CAPTION_POSITION_CHOICES,
        "video_filters": ClientProject.VIDEO_FILTER_CHOICES,
        "error": "",
    })


# ── Project detail / episodes ──────────────────────────────────────────

@csrf_exempt
def project_detail(request, project_id):
    project = get_object_or_404(ClientProject, pk=project_id)
    if request.method == "POST" and request.POST.get("action") == "update_settings":
        project.caption_template = request.POST.get("caption_template", project.caption_template)
        project.caption_font = request.POST.get("caption_font", project.caption_font)
        project.caption_color = request.POST.get("caption_color", project.caption_color)
        project.caption_position = request.POST.get("caption_position", project.caption_position)
        project.video_filter = request.POST.get("video_filter", project.video_filter)
        project.default_template = request.POST.get("default_template", project.default_template)
        project.brand_lower_third = request.POST.get("brand_lower_third", "").strip()
        project.zoom_punch = "zoom_punch" in request.POST
        project.master_audio = "master_audio" in request.POST
        project.hook_card = "hook_card" in request.POST
        project.podcast_solo_switch = "podcast_solo_switch" in request.POST
        project.save()
        return redirect(f"{reverse('project_detail', kwargs={'project_id': project.pk})}?msg={quote('Project settings updated.')}")

    episodes = []
    for ep in project.episodes.all():
        color, message, counts = _episode_state(ep)
        episodes.append({"episode": ep, "color": color, "message": message, "counts": counts})
    rail = "red"
    order = {"red": 0, "amber": 1, "green": 2, "off": 3}
    if episodes:
        rail = min((e["color"] for e in episodes), key=lambda c: order[c])
    return render(request, "webui/project_detail.html", {
        "project": project,
        "episodes": episodes,
        "tally": rail,
        "caption_templates": ClientProject.CAPTION_TEMPLATE_CHOICES,
        "fonts": ClientProject.CAPTION_FONT_CHOICES,
        "positions": ClientProject.CAPTION_POSITION_CHOICES,
        "video_filters": ClientProject.VIDEO_FILTER_CHOICES,
        "error": request.GET.get("error", ""),
        "msg": request.GET.get("msg", ""),
    })


@csrf_exempt
def episode_add(request, project_id):
    project = get_object_or_404(ClientProject, pk=project_id)
    if request.method != "POST":
        return redirect("project_detail", project_id=project.pk)
    url = request.POST.get("url", "").strip()
    local_path = request.POST.get("path", "").strip()
    fmt = request.POST.get("fmt", "1080").strip() or "1080"
    if not url and not local_path:
        return redirect(f"{reverse('project_detail', kwargs={'project_id': project.pk})}?error={quote('Provide a YouTube URL or a local video file.')}")

    out_dir = Path(settings.OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from shorts_generator.local.downloader import download_youtube_local
        from shorts_generator.local.transcriber import transcribe_local

        cookies_path = None
        if "cookies_file" in request.FILES:
            up_cookies = request.FILES["cookies_file"]
            c_target = out_dir / "cookies.txt"
            with open(c_target, "wb") as f:
                for chunk in up_cookies.chunks():
                    f.write(chunk)
            cookies_path = str(c_target)

        if url:
            source_path = Path(download_youtube_local(url, fmt=fmt, cookies_path=cookies_path))
            video_id = source_path.stem.replace("source_", "", 1)
            if not str(source_path).startswith(str(out_dir)):
                target = out_dir / f"source_{video_id}.mp4"
                if not target.exists() or target.stat().st_size != source_path.stat().st_size:
                    shutil.copy2(source_path, target)
                source_path = target
        else:
            src = Path(local_path).expanduser()
            if not src.exists():
                raise RuntimeError(f"Local file not found: {local_path}")
            video_id = re.sub(r"[^A-Za-z0-9_-]", "_", src.stem)
            target = out_dir / f"source_{video_id}.mp4"
            if not target.exists() or target.stat().st_size != src.stat().st_size:
                shutil.copy2(src, target)
            source_path = target

        transcript = transcribe_local(str(source_path))
        if not transcript.get("segments"):
            raise RuntimeError("Whisper produced no segments.")

        title = _read_video_title(video_id)
        episode = Episode.objects.create(
            project=project,
            video_id=video_id,
            title=title or video_id,
            source_file=str(source_path),
        )
        return redirect("episode_mark", episode_id=episode.pk)
    except Exception as exc:
        return redirect(f"{reverse('project_detail', kwargs={'project_id': project.pk})}?error={quote(str(exc))}")


# ── Mark clips ─────────────────────────────────────────────────────────

def episode_mark(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    segments = _transcript_for(episode.video_id)
    if segments is None:
        return render(request, "webui/episode_mark.html", {
            "episode": episode,
            "segments": [],
            "clips": [],
            "tally": "red",
            "error": "No transcript found. Re-add the episode to transcribe it.",
        })
    for seg in segments:
        seg["ts"] = _fmt_ts(seg["start"])
        seg["te"] = _fmt_ts(seg["end"])

    clips = list(episode.clips.all())
    for c in clips:
        c.start_ts = _fmt_ts(c.start_time)
        c.end_ts = _fmt_ts(c.end_time)
        c.duration_ts = _fmt_ts(c.duration)

    color, message, counts = _episode_state(episode)
    active_job = episode.render_jobs.exclude(
        status__in=[RenderJob.STATUS_DONE, RenderJob.STATUS_FAILED, RenderJob.STATUS_CANCELLED]
    ).first()
    return render(request, "webui/episode_mark.html", {
        "episode": episode,
        "segments": segments,
        "clips": clips,
        "tally": color,
        "state_message": message,
        "active_job": active_job,
        "msg": request.GET.get("msg", ""),
    })


@csrf_exempt
def clip_add(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    if request.method == "POST":
        try:
            start = float(request.POST.get("start", ""))
            end = float(request.POST.get("end", ""))
            if end > start:
                Clip.objects.create(episode=episode, start_time=start, end_time=end)
                return JsonResponse({"ok": True})
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "bad times"}, status=400)
    return JsonResponse({"ok": False}, status=405)


@csrf_exempt
def clip_delete(request, episode_id, clip_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    if request.method == "POST":
        Clip.objects.filter(pk=clip_id, episode=episode).delete()
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False}, status=405)


# ── Async batch render ─────────────────────────────────────────────────

def start_render_job(episode: Episode) -> RenderJob:
    from .jobs import run_render_job
    job = RenderJob.objects.create(episode=episode, status=RenderJob.STATUS_QUEUED)
    from threading import Thread
    t = Thread(target=run_render_job, args=(job.pk,), daemon=True)
    t.start()
    return job


@csrf_exempt
def episode_render(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    if request.method != "POST":
        return redirect("episode_mark", episode_id=episode.pk)
    if not episode.clips.exists():
        return redirect("episode_mark", episode_id=episode.pk)
    # Don't stack duplicate jobs for the same episode.
    active = episode.render_jobs.exclude(
        status__in=[RenderJob.STATUS_DONE, RenderJob.STATUS_FAILED, RenderJob.STATUS_CANCELLED]
    ).exists()
    if active:
        return redirect("episode_mark", episode_id=episode.pk)
    start_render_job(episode)
    return redirect("episode_mark", episode_id=episode.pk)


@csrf_exempt
def render_cancel(request, episode_id):
    """Cancel any queued or running batch render for this episode."""
    episode = get_object_or_404(Episode, pk=episode_id)
    from .jobs import cancel_job_in_memory
    active_jobs = episode.render_jobs.exclude(
        status__in=[RenderJob.STATUS_DONE, RenderJob.STATUS_FAILED, RenderJob.STATUS_CANCELLED]
    )
    for job in active_jobs:
        job.status = RenderJob.STATUS_CANCELLED
        job.message = "Cancelled by user"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "message", "finished_at"])
        cancel_job_in_memory(job.pk)
    return JsonResponse({"ok": True, "status": "cancelled"})


def render_status(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    job = episode.render_jobs.first()
    if job is None:
        return JsonResponse({"status": "none"})
    return JsonResponse({
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "finished": job.finished_at.isoformat() if job.finished_at else None,
    })


# ── Quick clip review ──────────────────────────────────────────────────

def _review_clips(episode: Episode):
    """Return [{clip, short_url, size, index}] for rendered clips."""
    clips = list(episode.clips.all())
    out = []
    for i, clip in enumerate(clips, 1):
        name = _short_name(episode, i)
        path = Path(settings.OUTPUT_DIR) / name
        short_url = reverse("serve_output", args=[name]) if path.exists() else None
        size = path.stat().st_size if path.exists() else 0
        out.append({"clip": clip, "short_url": short_url, "size": size, "index": i})
    return out


def episode_review(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    clips = _review_clips(episode)
    if not clips:
        return redirect("episode_mark", episode_id=episode.pk)
    # Stepper: honor ?idx, else first unconfirmed clip, else last.
    try:
        wanted = int(request.GET.get("idx", "") or 0)
        current = next((c for c in clips if c["index"] == wanted), None)
    except ValueError:
        current = None
    if current is None:
        current = next((c for c in clips if not c["clip"].confirmed), clips[-1])
    color = "green" if all(c["clip"].confirmed for c in clips) else "red"
    templates = [
        ("full_bleed_solo", "Full Bleed 9:16 (Edge-to-Edge)"),
        ("blurred_backdrop", "Blurred Backdrop (Wide Focus)"),
        ("stage_solo_speaker", "Stage Solo (Safe-Zone Padded)"),
        ("podcast_split_screen", "Podcast Split Screen (Two Hosts)"),
    ]
    return render(request, "webui/episode_review.html", {
        "episode": episode,
        "clips": clips,
        "current": current,
        "current_idx": current["index"],
        "total": len(clips),
        "tally": color,
        "templates": templates,
        "caption_templates": ClientProject.CAPTION_TEMPLATE_CHOICES,
        "video_filters": ClientProject.VIDEO_FILTER_CHOICES,
        "msg": request.GET.get("msg", ""),
    })


@csrf_exempt
def clip_confirm(request, episode_id, clip_id):
    clip = get_object_or_404(Clip, pk=clip_id, episode_id=episode_id)
    if request.method == "POST":
        clip.confirmed = True
        if request.POST.get("caption", "").strip():
            clip.caption_override = request.POST.get("caption", "").strip()
        clip.save()
        return redirect("episode_review", episode_id=episode_id)
    return redirect("episode_review", episode_id=episode_id)


@csrf_exempt
def clip_trim(request, episode_id, clip_id):
    """Adjust a clip's in/out and settings, then re-render just that clip synchronously."""
    episode = get_object_or_404(Episode, pk=episode_id)
    clip = get_object_or_404(Clip, pk=clip_id, episode=episode)
    if request.method == "POST":
        try:
            start_raw = request.POST.get("start")
            end_raw = request.POST.get("end")
            if start_raw is not None and end_raw is not None:
                start = float(start_raw)
                end = float(end_raw)
                if end > start:
                    clip.start_time = start
                    clip.end_time = end
            if "caption" in request.POST:
                clip.caption_override = request.POST.get("caption", "").strip()
            clip.save()

            template_override = request.POST.get("template")
            if template_override:
                episode.project.default_template = template_override
                episode.project.save(update_fields=["default_template"])

            caption_tmpl_override = request.POST.get("caption_template")
            if caption_tmpl_override:
                episode.project.caption_template = caption_tmpl_override
                episode.project.save(update_fields=["caption_template"])

            video_filter_override = request.POST.get("video_filter")
            if video_filter_override:
                episode.project.video_filter = video_filter_override
                episode.project.save(update_fields=["video_filter"])
        except (TypeError, ValueError):
            pass
    clips = sorted(episode.clips.all(), key=lambda c: c.start_time)
    idx = clips.index(clip) + 1
    out_path = Path(settings.OUTPUT_DIR) / _short_name(episode, idx)
    try:
        from .jobs import render_one_clip
        render_one_clip(episode, clip, idx, out_path)
        msg = "Clip re-rendered with agency production engine."
    except Exception as exc:
        msg = f"Re-render failed: {exc}"
    return redirect(f"{reverse('episode_review', kwargs={'episode_id': episode_id})}?idx={idx}&msg={quote(msg)}")


# ── Package & deliver ──────────────────────────────────────────────────

def episode_deliver(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    clips = _review_clips(episode)
    color, message, counts = _episode_state(episode)
    zip_rel = f"deliveries/{episode.project.slug}/{episode.pk:04d}_batch.zip"
    return render(request, "webui/episode_deliver.html", {
        "episode": episode,
        "clips": clips,
        "tally": color if episode.delivered else "amber",
        "zip_rel": zip_rel,
        "zip_exists": (Path(settings.OUTPUT_DIR) / zip_rel).exists(),
        "msg": request.GET.get("msg", ""),
    })


@csrf_exempt
def episode_package(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    if request.method != "POST":
        return redirect("episode_deliver", episode_id=episode.pk)

    out_dir = Path(settings.OUTPUT_DIR)
    delivery_dir = out_dir / "deliveries" / episode.project.slug / f"{episode.pk:04d}"
    delivery_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for i, clip in enumerate(sorted(episode.clips.all(), key=lambda c: c.start_time), 1):
        name = _short_name(episode, i)
        src = out_dir / name
        if src.exists():
            dest = delivery_dir / f"{episode.project.slug}_{episode.pk:04d}_clip{i:02d}.mp4"
            shutil.copy2(src, dest)
            copied.append(dest)

    zip_path = out_dir / "deliveries" / episode.project.slug / f"{episode.pk:04d}_batch.zip"
    if copied:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in copied:
                zf.write(f, arcname=f.name)
        episode.delivered = True
        episode.save(update_fields=["delivered"])
    return redirect(f"{reverse('episode_deliver', kwargs={'episode_id': episode.pk})}?msg={quote('Packaged & marked delivered.')}")


# ── Transcript / output serving ────────────────────────────────────────

def download_transcript(request, video_id):
    srt_path = Path(settings.OUTPUT_DIR) / f"source_{video_id}.srt"
    words_path = Path(settings.OUTPUT_DIR) / f"source_{video_id}.words.json"
    if not srt_path.exists() and not words_path.exists():
        raise Http404("Transcript not found for this video")

    fmt = request.GET.get("format", "srt").lower().strip()

    # Resolve friendly sanitized filename from title
    title = _read_video_title(video_id)
    if not title:
        ep = Episode.objects.filter(video_id=video_id).first()
        if ep and ep.title:
            title = ep.title
    clean_title = re.sub(r'[^\w\-_\. ]', '_', title).strip() if title else ""
    clean_title = re.sub(r' +', '_', clean_title).strip('_')
    base_name = f"{clean_title}_transcript" if clean_title else f"transcript_{video_id}"

    if fmt in ("txt", "text", "clean"):
        include_ts = fmt != "clean" and request.GET.get("timestamps", "1") != "0"
        lines = []
        if srt_path.exists():
            from shorts_generator.local.transcriber import _load_srt_cache
            cached = _load_srt_cache(srt_path)
            segments = cached.get("segments") or _parse_srt(srt_path)
            for s in segments:
                if include_ts:
                    ts_str = _fmt_ts(s["start"]).split(",")[0]
                    lines.append(f"[{ts_str}] {s['text']}")
                else:
                    lines.append(s["text"])
        elif words_path.exists():
            data = json.loads(words_path.read_text(encoding="utf-8"))
            for seg in data:
                if isinstance(seg, list) and seg:
                    seg_text = " ".join(w.get("word", "") for w in seg)
                    if include_ts:
                        ts_str = _fmt_ts(seg[0].get("start", 0)).split(",")[0]
                        lines.append(f"[{ts_str}] {seg_text}")
                    else:
                        lines.append(seg_text)
        content = "\n".join(lines)
        response = HttpResponse(content, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{base_name}.txt"'
        return response

    elif fmt == "json":
        if words_path.exists():
            response = FileResponse(
                open(words_path, "rb"),
                content_type="application/json",
            )
        elif srt_path.exists():
            segments = _parse_srt(srt_path)
            response = HttpResponse(
                json.dumps(segments, indent=2),
                content_type="application/json; charset=utf-8",
            )
        else:
            raise Http404()
        response["Content-Disposition"] = f'attachment; filename="{base_name}.json"'
        return response

    else:
        # Default: SRT
        if not srt_path.exists():
            raise Http404("SRT transcript not found")
        response = FileResponse(
            open(srt_path, "rb"),
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="{base_name}.srt"'
        return response


def download_episode_transcript(request, episode_id):
    episode = get_object_or_404(Episode, pk=episode_id)
    return download_transcript(request, episode.video_id)


def _file_response(request, path: Path, content_type: str) -> HttpResponse:
    size = path.stat().st_size
    range_header = request.META.get("HTTP_RANGE", "")
    if range_header:
        m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
        if m:
            start_s, end_s = m.groups()
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            if start >= size:
                response = HttpResponse(status=416)
                response["Content-Range"] = f"bytes */{size}"
                return response
            end = min(end, size - 1)
            length = end - start + 1
            with open(path, "rb") as f:
                f.seek(start)
                chunk = f.read(length)
            response = HttpResponse(chunk, status=206, content_type=content_type)
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
            response["Content-Length"] = str(length)
            response["Accept-Ranges"] = "bytes"
            return response
    response = FileResponse(open(path, "rb"), content_type=content_type)
    response["Content-Length"] = str(size)
    response["Accept-Ranges"] = "bytes"
    return response


def _mime_for(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext in (".webm",):
        return "video/webm"
    if ext in (".mp3",):
        return "audio/mpeg"
    if ext in (".wav",):
        return "audio/wav"
    if ext in (".m4a", ".aac"):
        return "audio/mp4"
    if ext in (".ogg",):
        return "audio/ogg"
    if ext in (".srt",):
        return "text/plain"
    if ext == ".zip":
        return "application/zip"
    if ext in (".png",):
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def serve_output(request, filename):
    path = Path(settings.OUTPUT_DIR) / filename
    if not path.exists() or not path.is_file():
        raise Http404()
    return _file_response(request, path, _mime_for(path.name))


# ── FreeCut browser editor (advanced mode) ─────────────────────────────

_EDITOR_MIME = {
    ext: ct
    for ext, ct in [
        (".html", "text/html; charset=utf-8"),
        (".js", "text/javascript; charset=utf-8"),
        (".mjs", "text/javascript; charset=utf-8"),
        (".css", "text/css; charset=utf-8"),
        (".json", "application/json"),
        (".map", "application/json"),
        (".webmanifest", "application/manifest+json"),
        (".svg", "image/svg+xml"),
        (".png", "image/png"),
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".webp", "image/webp"),
        (".gif", "image/gif"),
        (".avif", "image/avif"),
        (".ico", "image/x-icon"),
        (".wasm", "application/wasm"),
        (".woff", "font/woff"),
        (".woff2", "font/woff2"),
        (".ttf", "font/ttf"),
        (".otf", "font/otf"),
        (".onnx", "application/octet-stream"),
        (".bin", "application/octet-stream"),
        (".mp3", "audio/mpeg"),
        (".wav", "audio/wav"),
    ]
}


def _isolated_headers(response):
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    response["Cross-Origin-Embedder-Policy"] = "require-corp"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    return response


def _collect_exports():
    ws = Path(settings.FREECUT_WORKSPACE)
    exports = []
    if ws.is_dir():
        for p in ws.glob("projects/*/exports/*.mp4"):
            try:
                st = p.stat()
            except OSError:
                continue
            exports.append({
                "name": p.name,
                "path": str(p.relative_to(ws)).replace("\\", "/"),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
    exports.sort(key=lambda e: e["mtime"], reverse=True)
    return exports


def freecut_exports(request):
    return JsonResponse({"exports": _collect_exports()})


@csrf_exempt
def editor_app(request, path=""):
    dist = Path(settings.FREECUT_DIST)
    if not dist.is_dir():
        return _isolated_headers(HttpResponse(
            "FreeCut editor build is missing. Rebuild it with "
            "`npm ci && npm run build` in vendor/freecut.",
            status=500,
        ))
    rel = (path or "index.html").replace("\\", "/")
    if rel.startswith("/") or ".." in rel.split("/"):
        return _isolated_headers(HttpResponseNotFound("not found"))
    target = (dist / rel).resolve()
    if not str(target).startswith(str(dist.resolve())):
        return _isolated_headers(HttpResponseNotFound("not found"))
    if target.is_dir():
        target = target / "index.html"
    if target.is_file():
        content_type = _EDITOR_MIME.get(target.suffix.lower(), "application/octet-stream")
        return _isolated_headers(_file_response(request, target, content_type))
    if not target.suffix:
        index_html = dist / "index.html"
        if index_html.is_file():
            return _isolated_headers(_file_response(
                request, index_html, _EDITOR_MIME[".html"]))
    return _isolated_headers(HttpResponseNotFound("not found"))


def editor_shell(request, video_id):
    out_dir = Path(settings.OUTPUT_DIR)
    source_path = out_dir / f"source_{video_id}.mp4"
    if not source_path.exists():
        return redirect("home")
    source_url = reverse("serve_output", args=[source_path.name])
    return _isolated_headers(render(request, "webui/editor_shell.html", {
        "video_id": video_id,
        "filename": source_path.name,
        "duration": float(_ffprobe(source_path)) or 0,
        "source_url": source_url,
        "has_srt": (out_dir / f"source_{video_id}.srt").exists(),
        "srt_url": reverse("download_transcript", args=[video_id]),
        "workspace": str(Path(settings.FREECUT_WORKSPACE)),
        "editor_url": reverse("editor_app"),
        "editor_start_url": reverse("editor_app") + "projects",
        "exports": _collect_exports(),
    }))
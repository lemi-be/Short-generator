import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from webui.models import ClientProject, Episode, Clip, RenderJob, slugify
from webui.jobs import (
    cancel_job_in_memory,
    is_job_cancelled,
    JobCancellationToken,
    register_running_job,
    unregister_running_job,
    recover_interrupted_jobs,
    is_valid_clip_render,
)
from webui.views import _short_name
from shorts_generator.segmenter import is_sentence_end, extract_words, resegment_by_sentences
from shorts_generator.local.downloader import _format_for, _extract_youtube_video_id, _resolve_local_path
from shorts_generator.local.clipper import (
    _ratio,
    _band_for_position,
    TEMPLATE_SPECS,
    SUBTITLE_TEMPLATES,
    apply_video_filter,
)


class ModelTests(TestCase):
    def test_client_project_slugify_and_defaults(self):
        project = ClientProject.objects.create(name="Acme Media Agency")
        self.assertEqual(project.slug, "acme_media_agency")
        self.assertEqual(project.caption_template, "hormozi_pop")
        self.assertEqual(project.caption_font, "impact")
        self.assertEqual(project.default_template, "full_bleed_solo")
        self.assertTrue(project.zoom_punch)
        self.assertTrue(project.master_audio)
        self.assertTrue(project.hook_card)
        self.assertTrue(project.podcast_solo_switch)
        self.assertEqual(str(project), "Acme Media Agency")

    def test_client_project_slug_deduplication(self):
        p1 = ClientProject.objects.create(name="Tech Talk")
        p2 = ClientProject.objects.create(name="Tech! Talk")
        self.assertEqual(p1.slug, "tech_talk")
        self.assertEqual(p2.slug, "tech_talk_1")

    def test_episode_and_clip_models(self):
        project = ClientProject.objects.create(name="Client A")
        episode = Episode.objects.create(
            project=project,
            video_id="test1234",
            title="Episode 1",
            source_file="output/source_test1234.mp4",
        )
        self.assertIn("Client A", str(episode))

        clip = Clip.objects.create(
            episode=episode,
            start_time=10.5,
            end_time=35.0,
            caption_override="Opening hook",
        )
        self.assertAlmostEqual(clip.duration, 24.5)
        self.assertFalse(clip.confirmed)
        self.assertIn("10.5-35.0", str(clip))

    def test_render_job_and_cancellation(self):
        project = ClientProject.objects.create(name="Client B")
        episode = Episode.objects.create(project=project, video_id="ep2")
        job = RenderJob.objects.create(episode=episode)
        self.assertEqual(job.status, RenderJob.STATUS_QUEUED)
        self.assertEqual(job.progress, 0)

        # Test in-memory cancellation
        token = JobCancellationToken(job.pk)
        self.assertFalse(token.is_cancelled)
        cancel_job_in_memory(job.pk)
        self.assertTrue(is_job_cancelled(job.pk))
        self.assertTrue(token.is_cancelled)


class SegmenterTests(TestCase):
    def test_is_sentence_end(self):
        self.assertTrue(is_sentence_end("world."))
        self.assertTrue(is_sentence_end("really?"))
        self.assertTrue(is_sentence_end("now!"))
        self.assertTrue(is_sentence_end('quote."'))
        self.assertFalse(is_sentence_end("word"))
        self.assertFalse(is_sentence_end("Dr."))
        self.assertFalse(is_sentence_end("Mr."))
        self.assertFalse(is_sentence_end(""))

    def test_extract_words(self):
        data = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "hello world",
                    "words": [
                        {"start": 0.0, "end": 1.0, "word": "hello"},
                        {"start": 1.0, "end": 2.0, "word": "world."},
                    ],
                }
            ]
        }
        words = extract_words(data)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0]["word"], "hello")

    def test_resegment_by_sentences(self):
        words = [
            {"start": 0.0, "end": 0.5, "word": "This"},
            {"start": 0.5, "end": 1.0, "word": "is"},
            {"start": 1.0, "end": 1.5, "word": "first."},
            {"start": 2.0, "end": 2.5, "word": "Second"},
            {"start": 2.5, "end": 3.0, "word": "sentence!"},
        ]
        segments = resegment_by_sentences(words, min_words=2, min_duration=0.5, pause_threshold=0.3)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["text"], "This is first.")
        self.assertEqual(segments[1]["text"], "Second sentence!")
        self.assertAlmostEqual(segments[0]["start"], 0.0)
        self.assertAlmostEqual(segments[0]["end"], 1.5)


class DownloaderHelpersTests(TestCase):
    def test_format_for(self):
        self.assertIn("height<=1080", _format_for("1080"))
        self.assertIn("height<=720", _format_for("720"))
        self.assertEqual(_format_for("best"), "bestvideo+bestaudio/best")

    def test_extract_youtube_video_id(self):
        self.assertEqual(_extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(_extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(_extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(_extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(_extract_youtube_video_id("https://example.com/video.mp4"))

    def test_resolve_local_path(self):
        # A non-existent local path raises RuntimeError
        with self.assertRaises(RuntimeError):
            _resolve_local_path("non_existent_folder/video.mp4")


class ClipperHelpersTests(TestCase):
    def test_ratio(self):
        self.assertAlmostEqual(_ratio("9:16"), 9.0 / 16.0)
        self.assertAlmostEqual(_ratio("invalid"), 9.0 / 16.0)

    def test_band_for_position(self):
        # Full bleed / single focus positions
        top_band = _band_for_position("top", "single_focus")
        self.assertEqual(top_band, (320, 620))
        lower_band = _band_for_position("lower_third", "single_focus")
        self.assertEqual(lower_band, (1180, 1500))

        # Split screen center seam vs solo view
        split_dual = _band_for_position("lower_third", "split_vertical", is_solo=False)
        self.assertEqual(split_dual, (860, 1060))
        split_solo = _band_for_position("lower_third", "split_vertical", is_solo=True)
        self.assertEqual(split_solo, (1400, 1660))

    def test_templates_and_subtitles_specs(self):
        self.assertIn("full_bleed_solo", TEMPLATE_SPECS)
        self.assertIn("podcast_split_screen", TEMPLATE_SPECS)
        self.assertIn("stage_solo_speaker", TEMPLATE_SPECS)
        self.assertIn("blurred_backdrop", TEMPLATE_SPECS)

        self.assertIn("hormozi_pop", SUBTITLE_TEMPLATES)
        self.assertIn("beast_neon", SUBTITLE_TEMPLATES)
        self.assertIn("minimal_clean", SUBTITLE_TEMPLATES)
        self.assertIn("documentary", SUBTITLE_TEMPLATES)
        self.assertIn("cyber_terminal", SUBTITLE_TEMPLATES)

    def test_apply_video_filter(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        out_none = apply_video_filter(frame, "none")
        self.assertEqual(out_none.shape, (100, 100, 3))
        out_vivid = apply_video_filter(frame, "vivid_pop")
        self.assertEqual(out_vivid.shape, (100, 100, 3))


class WebViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.project = ClientProject.objects.create(name="Test Studio")
        self.episode = Episode.objects.create(
            project=self.project,
            video_id="sample_vid",
            title="Sample Interview",
        )

    def test_home_view(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Studio")

    def test_project_new_get_and_post(self):
        response = self.client.get(reverse("project_new"))
        self.assertEqual(response.status_code, 200)

        response = self.client.post(reverse("project_new"), {
            "name": "New Client Brand",
            "caption_template": "beast_neon",
            "caption_font": "heavy",
            "caption_color": "#00F0FF",
            "caption_position": "lower_third",
            "video_filter": "vivid_pop",
            "default_template": "full_bleed_solo",
            "zoom_punch": "on",
            "master_audio": "on",
        })
        self.assertEqual(response.status_code, 302)
        created = ClientProject.objects.filter(name="New Client Brand").first()
        self.assertIsNotNone(created)
        self.assertEqual(created.caption_template, "beast_neon")

    def test_project_detail_view(self):
        response = self.client.get(reverse("project_detail", args=[self.project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Studio")

    def test_clip_add_and_delete(self):
        add_url = reverse("clip_add", args=[self.episode.pk])
        response = self.client.post(add_url, {"start": "5.0", "end": "25.0"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))
        clip = self.episode.clips.first()
        self.assertIsNotNone(clip)
        self.assertAlmostEqual(clip.start_time, 5.0)
        self.assertAlmostEqual(clip.end_time, 25.0)

        del_url = reverse("clip_delete", args=[self.episode.pk, clip.pk])
        response = self.client.post(del_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))
        self.assertEqual(self.episode.clips.count(), 0)

    def test_render_status_empty_and_active(self):
        status_url = reverse("render_status", args=[self.episode.pk])
        response = self.client.get(status_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "none")

        job = RenderJob.objects.create(episode=self.episode, progress=45, status=RenderJob.STATUS_RENDERING)
        register_running_job(job.pk)
        try:
            response = self.client.get(status_url)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], RenderJob.STATUS_RENDERING)
            self.assertEqual(data["progress"], 45)
        finally:
            unregister_running_job(job.pk)

    def test_episode_mark_view(self):
        response = self.client.get(reverse("episode_mark", args=[self.episode.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sample Interview")


class PipelineAndHighlightsTests(TestCase):
    def test_pipeline_mode_validation(self):
        from shorts_generator.pipeline import generate_shorts
        with self.assertRaises(ValueError):
            generate_shorts("https://example.com/video.mp4", mode="api")
        with self.assertRaises(ValueError):
            generate_shorts("https://example.com/video.mp4", mode="cloud")

    def test_dedupe_highlights_overlap(self):
        from shorts_generator.highlights import dedupe_highlights
        highlights = [
            {"title": "High score", "score": 90, "start_time": 10.0, "end_time": 40.0},
            {"title": "Overlapping lower score", "score": 70, "start_time": 15.0, "end_time": 42.0},
            {"title": "Distinct later clip", "score": 85, "start_time": 60.0, "end_time": 90.0},
        ]
        kept = dedupe_highlights(highlights)
        self.assertEqual(len(kept), 2)
        titles = [h["title"] for h in kept]
        self.assertIn("High score", titles)
        self.assertIn("Distinct later clip", titles)
        self.assertNotIn("Overlapping lower score", titles)

    def test_sanitize_highlights_bounds(self):
        from shorts_generator.highlights import _sanitize_highlights
        raw = [
            {"title": "Valid", "start_time": 10.0, "end_time": 45.0, "score": 88},
            {"title": "Too short", "start_time": 10.0, "end_time": 15.0, "score": 90},
            {"title": "Too long", "start_time": 0.0, "end_time": 120.0, "score": 95},
        ]
        sanitized = _sanitize_highlights(raw, duration=200.0, min_seconds=30, max_seconds=60)
        self.assertEqual(len(sanitized), 2)
        # Check that "Too long" was clamped to max 60s
        long_clip = next(c for c in sanitized if c["title"] == "Too long")
        self.assertAlmostEqual(long_clip["end_time"] - long_clip["start_time"], 60.0)


class CSRFSecurityTests(TestCase):
    def setUp(self):
        self.csrf_client = Client(enforce_csrf_checks=True)
        self.project = ClientProject.objects.create(name="CSRF Test Project")
        self.episode = Episode.objects.create(project=self.project, video_id="csrf123")
        self.clip = Clip.objects.create(episode=self.episode, start_time=1.0, end_time=10.0)

    def test_csrf_rejection_without_token(self):
        """All browser state-changing endpoints must reject requests without a CSRF token with 403."""
        endpoints = [
            (reverse("project_new"), {"name": "Malicious Project"}),
            (reverse("project_detail", args=[self.project.pk]), {"action": "update_settings"}),
            (reverse("clip_add", args=[self.episode.pk]), {"start": "1.0", "end": "5.0"}),
            (reverse("clip_delete", args=[self.episode.pk, self.clip.pk]), {}),
            (reverse("episode_render", args=[self.episode.pk]), {}),
            (reverse("render_cancel", args=[self.episode.pk]), {}),
            (reverse("clip_confirm", args=[self.episode.pk, self.clip.pk]), {}),
            (reverse("clip_trim", args=[self.episode.pk, self.clip.pk]), {"start": "2.0", "end": "8.0"}),
            (reverse("episode_package", args=[self.episode.pk]), {}),
        ]
        for url, data in endpoints:
            with self.subTest(url=url):
                res = self.csrf_client.post(url, data)
                self.assertEqual(res.status_code, 403, f"Expected 403 on {url} without CSRF token, got {res.status_code}")

    def test_csrf_accepted_with_valid_token(self):
        """State-changing requests with valid CSRF tokens must be accepted."""
        get_res = self.csrf_client.get(reverse("episode_mark", args=[self.episode.pk]))
        self.assertEqual(get_res.status_code, 200)
        self.assertIn("csrftoken", get_res.cookies)
        token = get_res.cookies["csrftoken"].value

        add_res = self.csrf_client.post(
            reverse("clip_add", args=[self.episode.pk]),
            {"start": "12.0", "end": "22.0"},
            headers={"x-csrftoken": token},
        )
        self.assertEqual(add_res.status_code, 200)
        self.assertTrue(add_res.json().get("ok"))


class DeliveryIntegrityTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.project = ClientProject.objects.create(name="Delivery Test Brand")
        self.episode = Episode.objects.create(
            project=self.project,
            video_id="delivery_vid",
            source_file=str(self.output_dir / "source_delivery_vid.mp4"),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_delivery_rejected_when_no_clips(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("error=", res.url)
            self.episode.refresh_from_db()
            self.assertFalse(self.episode.delivered)

    def test_delivery_rejected_with_unapproved_clips(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            clip = Clip.objects.create(episode=self.episode, start_time=5.0, end_time=15.0, confirmed=False)
            name = _short_name(self.episode, 1)
            mp4_file = self.output_dir / name
            mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video-content")
            meta_file = self.output_dir / f"{mp4_file.stem}.meta.json"
            meta_file.write_text(json.dumps({
                "clip_id": clip.pk,
                "source_start": 5.0,
                "source_end": 15.0,
                "caption_override": "",
                "status": "complete",
            }), encoding="utf-8")

            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("error=", res.url)
            self.assertTrue("not%20approved" in res.url or "not+approved" in res.url)
            self.episode.refresh_from_db()
            self.assertFalse(self.episode.delivered)

    def test_delivery_rejected_with_missing_renders(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            Clip.objects.create(episode=self.episode, start_time=5.0, end_time=15.0, confirmed=True)
            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("error=", res.url)
            self.assertIn("missing", res.url)
            self.episode.refresh_from_db()
            self.assertFalse(self.episode.delivered)

    def test_delivery_rejected_with_stale_timestamp_render(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            clip = Clip.objects.create(episode=self.episode, start_time=10.0, end_time=20.0, confirmed=True)
            name = _short_name(self.episode, 1)
            mp4_file = self.output_dir / name
            mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video-content")
            meta_file = self.output_dir / f"{mp4_file.stem}.meta.json"
            # Metadata has older timestamps 5.0 - 15.0
            meta_file.write_text(json.dumps({
                "clip_id": clip.pk,
                "source_start": 5.0,
                "source_end": 15.0,
                "caption_override": "",
                "status": "complete",
            }), encoding="utf-8")

            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("stale", res.url)
            self.episode.refresh_from_db()
            self.assertFalse(self.episode.delivered)

    def test_delivery_rejected_with_stale_caption_render(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            clip = Clip.objects.create(episode=self.episode, start_time=5.0, end_time=15.0, caption_override="Updated Hook", confirmed=True)
            name = _short_name(self.episode, 1)
            mp4_file = self.output_dir / name
            mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video-content")
            meta_file = self.output_dir / f"{mp4_file.stem}.meta.json"
            meta_file.write_text(json.dumps({
                "clip_id": clip.pk,
                "source_start": 5.0,
                "source_end": 15.0,
                "caption_override": "Old Hook",
                "status": "complete",
            }), encoding="utf-8")

            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("stale", res.url)
            self.episode.refresh_from_db()
            self.assertFalse(self.episode.delivered)

    def test_delivery_successful_packaging(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            clip1 = Clip.objects.create(episode=self.episode, start_time=5.0, end_time=15.0, confirmed=True)
            clip2 = Clip.objects.create(episode=self.episode, start_time=20.0, end_time=30.0, confirmed=True)

            for i, clip in enumerate([clip1, clip2], 1):
                name = _short_name(self.episode, i)
                mp4_file = self.output_dir / name
                mp4_file.write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video-data")
                meta_file = self.output_dir / f"{mp4_file.stem}.meta.json"
                meta_file.write_text(json.dumps({
                    "clip_id": clip.pk,
                    "source_start": clip.start_time,
                    "source_end": clip.end_time,
                    "caption_override": "",
                    "status": "complete",
                }), encoding="utf-8")

            res = self.client.post(reverse("episode_package", args=[self.episode.pk]))
            self.assertEqual(res.status_code, 302)
            self.assertIn("msg=Packaged", res.url)

            self.episode.refresh_from_db()
            self.assertTrue(self.episode.delivered)

            zip_path = self.output_dir / "deliveries" / self.project.slug / f"{self.episode.pk:04d}_batch.zip"
            self.assertTrue(zip_path.exists())
            self.assertGreater(zip_path.stat().st_size, 0)


class ClipEditCorrectnessTests(TestCase):
    def setUp(self):
        self.project = ClientProject.objects.create(
            name="Edit Test Project",
            default_template="full_bleed_solo",
            caption_template="hormozi_pop",
            video_filter="vivid_pop",
        )
        self.episode = Episode.objects.create(
            project=self.project,
            video_id="edit_vid",
            delivered=True,
        )
        self.clip = Clip.objects.create(
            episode=self.episode,
            start_time=10.0,
            end_time=25.0,
            confirmed=True,
        )

    @patch("webui.jobs.render_one_clip")
    def test_clip_edit_invalidates_approval_and_delivery(self, mock_render):
        trim_url = reverse("clip_trim", args=[self.episode.pk, self.clip.pk])
        res = self.client.post(trim_url, {"start": "12.0", "end": "28.0"})
        self.assertEqual(res.status_code, 302)

        self.clip.refresh_from_db()
        self.assertAlmostEqual(self.clip.start_time, 12.0)
        self.assertAlmostEqual(self.clip.end_time, 28.0)
        self.assertFalse(self.clip.confirmed, "Clip approval must be invalidated after edit")

        self.episode.refresh_from_db()
        self.assertFalse(self.episode.delivered, "Episode delivery status must be reset after clip edit")

    @patch("webui.jobs.render_one_clip")
    def test_settings_isolation_does_not_modify_project_defaults(self, mock_render):
        trim_url = reverse("clip_trim", args=[self.episode.pk, self.clip.pk])
        res = self.client.post(trim_url, {
            "start": "10.0",
            "end": "25.0",
            "template": "podcast_split_screen",
            "caption_template": "beast_neon",
            "video_filter": "warm_studio",
        })
        self.assertEqual(res.status_code, 302)

        # Check render_one_clip was called with the overrides
        mock_render.assert_called_once()
        kwargs = mock_render.call_args[1]
        self.assertEqual(kwargs.get("template"), "podcast_split_screen")
        self.assertEqual(kwargs.get("caption_template"), "beast_neon")
        self.assertEqual(kwargs.get("video_filter"), "warm_studio")

        # Project defaults must remain UNCHANGED
        self.project.refresh_from_db()
        self.assertEqual(self.project.default_template, "full_bleed_solo")
        self.assertEqual(self.project.caption_template, "hormozi_pop")
        self.assertEqual(self.project.video_filter, "vivid_pop")

    @patch("webui.views._get_source_duration", return_value=60.0)
    def test_invalid_timestamps_rejected_with_error(self, mock_dur):
        trim_url = reverse("clip_trim", args=[self.episode.pk, self.clip.pk])

        # Negative start
        res = self.client.post(trim_url, {"start": "-5.0", "end": "20.0"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=", res.url)
        self.assertIn("negative", res.url)

        # End <= Start
        res = self.client.post(trim_url, {"start": "25.0", "end": "20.0"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=", res.url)
        self.assertIn("greater", res.url)

        # Exceeds duration
        res = self.client.post(trim_url, {"start": "10.0", "end": "75.0"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=", res.url)
        self.assertIn("exceeds", res.url)

        # Non-numeric
        res = self.client.post(trim_url, {"start": "abc", "end": "xyz"})
        self.assertEqual(res.status_code, 302)
        self.assertIn("error=", res.url)

        # Verify clip timestamps were NOT modified
        self.clip.refresh_from_db()
        self.assertAlmostEqual(self.clip.start_time, 10.0)
        self.assertAlmostEqual(self.clip.end_time, 25.0)

    @patch("webui.views._get_source_duration", return_value=60.0)
    def test_clip_add_invalid_timestamps(self, mock_dur):
        add_url = reverse("clip_add", args=[self.episode.pk])
        res = self.client.post(add_url, {"start": "70.0", "end": "80.0"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("exceeds", res.json().get("error", ""))


class RenderJobRecoveryTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)
        self.project = ClientProject.objects.create(name="Job Recovery Project")
        self.episode = Episode.objects.create(
            project=self.project,
            video_id="recovery_vid",
            source_file=str(self.output_dir / "source_recovery_vid.mp4"),
        )
        self.clip = Clip.objects.create(episode=self.episode, start_time=5.0, end_time=15.0)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_abandoned_job_marked_interrupted_on_recovery(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            job = RenderJob.objects.create(episode=self.episode, status=RenderJob.STATUS_RENDERING, progress=30)
            interrupted = recover_interrupted_jobs(self.episode)
            self.assertEqual(len(interrupted), 1)
            job.refresh_from_db()
            self.assertEqual(job.status, RenderJob.STATUS_FAILED)
            self.assertIn("Interrupted", job.message)
            self.assertIsNotNone(job.finished_at)

    def test_safe_retry_after_interrupted_job(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            job = RenderJob.objects.create(episode=self.episode, status=RenderJob.STATUS_QUEUED)
            status_url = reverse("render_status", args=[self.episode.pk])
            res = self.client.get(status_url)
            self.assertEqual(res.json()["status"], RenderJob.STATUS_FAILED)

            # Starting a new render is not blocked by abandoned job
            with patch("webui.views.start_render_job") as mock_start:
                mock_start.return_value = None
                render_res = self.client.post(reverse("episode_render", args=[self.episode.pk]))
                self.assertEqual(render_res.status_code, 302)
                mock_start.assert_called_once()

    def test_incomplete_output_files_cleaned_up_on_recovery(self):
        with override_settings(OUTPUT_DIR=self.output_dir):
            name = _short_name(self.episode, 1)
            partial_mp4 = self.output_dir / name
            partial_mp4.write_bytes(b"partial-data")

            RenderJob.objects.create(episode=self.episode, status=RenderJob.STATUS_RENDERING)
            recover_interrupted_jobs(self.episode)

            # Partial file must be removed and not treated as finished render
            self.assertFalse(partial_mp4.exists(), "Incomplete output file should be cleaned up")
            self.assertFalse(is_valid_clip_render(self.episode, self.clip, 1))


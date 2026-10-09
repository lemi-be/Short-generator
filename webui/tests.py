"""Unit tests for Short Factory (webui and core pipeline)."""
import json
import numpy as np
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse

from webui.models import ClientProject, Episode, Clip, RenderJob, slugify
from webui.jobs import cancel_job_in_memory, is_job_cancelled, JobCancellationToken
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
        response = self.client.get(status_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], RenderJob.STATUS_RENDERING)
        self.assertEqual(data["progress"], 45)

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

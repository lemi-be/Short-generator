import re
import unicodedata

from django.db import models


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "project"


class ClientProject(models.Model):
    """One paying client. Caption style + branding live here, set once,
    and are inherited by every episode and clip automatically."""

    CAPTION_FONT_CHOICES = [
        ("inter", "Inter (modern)"),
        ("serif", "Georgia (warm serif)"),
        ("mono", "JetBrains Mono (typewriter)"),
    ]
    CAPTION_POSITION_CHOICES = [
        ("lower_third", "Lower third"),
        ("center", "Center"),
        ("top", "Top"),
    ]

    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    caption_font = models.CharField(max_length=50, choices=CAPTION_FONT_CHOICES, default="inter")
    caption_color = models.CharField(max_length=9, default="#FFFFFF")
    caption_position = models.CharField(max_length=20, choices=CAPTION_POSITION_CHOICES, default="lower_third")

    # Branding files live under output/branding/<slug>/ (served via /output/).
    brand_logo = models.CharField(max_length=500, blank=True)
    brand_lower_third = models.CharField(max_length=200, blank=True)

    default_template = models.CharField(max_length=50, default="stage_solo_speaker")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
            suffix = 1
            while ClientProject.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{slugify(self.name)}_{suffix}"
                suffix += 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Episode(models.Model):
    """One source video (YouTube URL or local file) scoped to a client project."""

    project = models.ForeignKey(ClientProject, on_delete=models.CASCADE, related_name="episodes")
    video_id = models.CharField(max_length=200)
    title = models.CharField(max_length=500, blank=True)
    source_file = models.CharField(max_length=500, blank=True)
    delivered = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project.name} — {self.title or self.video_id}"


class Clip(models.Model):
    """A marked in/out range on an episode's transcript. Autosaved as you mark."""

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="clips")
    start_time = models.FloatField()
    end_time = models.FloatField()
    caption_override = models.TextField(blank=True)
    confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time"]

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def __str__(self):
        return f"{self.episode.video_id} {self.start_time:.1f}-{self.end_time:.1f}"


class RenderJob(models.Model):
    """A batch render running in a background thread for one episode."""

    STATUS_QUEUED = "queued"
    STATUS_RENDERING = "rendering"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_RENDERING, "Rendering"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="render_jobs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    progress = models.IntegerField(default=0)  # 0-100
    message = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
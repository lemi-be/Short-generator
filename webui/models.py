from django.db import models


class Clip(models.Model):
    video_id = models.CharField(max_length=200)
    start_time = models.FloatField()
    end_time = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

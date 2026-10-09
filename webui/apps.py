from django.apps import AppConfig
from django.core.signals import request_started


def _on_first_request(sender, **kwargs):
    from .jobs import ensure_startup_recovery
    ensure_startup_recovery()


class WebuiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "webui"

    def ready(self):
        request_started.connect(_on_first_request)

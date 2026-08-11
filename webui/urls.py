from django.urls import path, re_path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("download/", views.download, name="download"),
    path("transcribe/<str:video_id>/", views.transcribe, name="transcribe"),
    # Specific sub-paths under video/ MUST come before the generic video/<id>/
    # pattern, otherwise <str:video_id> will capture "/add", "/delete/...",
    # "/generate" as part of the id and route to clip_editor instead.
    path("video/<str:video_id>/add/", views.add_clip, name="add_clip"),
    path("video/<str:video_id>/delete/<int:clip_id>/", views.delete_clip, name="delete_clip"),
    path("video/<str:video_id>/generate/", views.generate, name="generate"),
    path("video/<str:video_id>/edit/", views.editor_shell, name="editor_shell"),
    path("editor/", views.editor_app, {"path": ""}, name="editor_app"),
    re_path(r"^editor/(?P<path>.+)$", views.editor_app, name="editor_app"),
    path("exports/", views.freecut_exports, name="freecut_exports"),
    path("auto-generate/", views.auto_generate, name="auto_generate"),
    path("video/<str:video_id>/", views.clip_editor, name="clip_editor"),
    path("transcript/<str:video_id>/download/", views.download_transcript, name="download_transcript"),
    re_path(r"^output/(?P<filename>.+)$", views.serve_output, name="serve_output"),
]

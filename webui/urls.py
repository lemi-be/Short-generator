from django.urls import path, re_path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("projects/new/", views.project_new, name="project_new"),
    path("projects/<int:project_id>/", views.project_detail, name="project_detail"),
    path("projects/<int:project_id>/add/", views.episode_add, name="episode_add"),

    path("episodes/<int:episode_id>/mark/", views.episode_mark, name="episode_mark"),
    path("episodes/<int:episode_id>/clips/", views.clip_add, name="clip_add"),
    path("episodes/<int:episode_id>/clips/<int:clip_id>/delete/", views.clip_delete, name="clip_delete"),
    path("episodes/<int:episode_id>/render/", views.episode_render, name="episode_render"),
    path("episodes/<int:episode_id>/render-status/", views.render_status, name="render_status"),
    path("episodes/<int:episode_id>/review/", views.episode_review, name="episode_review"),
    path("episodes/<int:episode_id>/clips/<int:clip_id>/confirm/", views.clip_confirm, name="clip_confirm"),
    path("episodes/<int:episode_id>/clips/<int:clip_id>/trim/", views.clip_trim, name="clip_trim"),
    path("episodes/<int:episode_id>/deliver/", views.episode_deliver, name="episode_deliver"),
    path("episodes/<int:episode_id>/package/", views.episode_package, name="episode_package"),

    path("video/<str:video_id>/edit/", views.editor_shell, name="editor_shell"),
    path("editor/", views.editor_app, {"path": ""}, name="editor_app"),
    re_path(r"^editor/(?P<path>.+)$", views.editor_app, name="editor_app"),
    path("exports/", views.freecut_exports, name="freecut_exports"),
    path("transcript/<str:video_id>/download/", views.download_transcript, name="download_transcript"),
    re_path(r"^output/(?P<filename>.+)$", views.serve_output, name="serve_output"),
]
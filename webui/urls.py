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
    path("video/<str:video_id>/trim/<str:filename>/", views.trim_short, name="trim_short"),
    path("video/<str:video_id>/upload-audio/", views.upload_audio, name="upload_audio"),
    path("video/<str:video_id>/upload-logo/", views.upload_logo, name="upload_logo"),
    path("video/<str:video_id>/sfx/<str:kind>/", views.sfx_generate, name="sfx_generate"),
    path("video/<str:video_id>/captions/<str:filename>/", views.captions_for_clip, name="captions_for_clip"),
    path("video/<str:video_id>/stock-add/", views.stock_add, name="stock_add"),
    path("fonts/", views.font_list, name="font_list"),
    path("stock-search/", views.stock_search, name="stock_search"),
    path("video/<str:video_id>/", views.clip_editor, name="clip_editor"),
    path("transcript/<str:video_id>/download/", views.download_transcript, name="download_transcript"),
    re_path(r"^output/(?P<filename>.+)$", views.serve_output, name="serve_output"),
]

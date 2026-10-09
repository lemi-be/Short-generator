import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "hc%g-ypi_z%w0gb851(kj4^q)6wca)^!8wu+ycpj^&5a24a8c2"
DEBUG = True
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "webui",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "webui.urls"
WSGI_APPLICATION = "webui.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "webui" / "db.sqlite3",
    }
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {},
    }
]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "webui" / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

OUTPUT_DIR = BASE_DIR / "output"

# FreeCut browser editor (vendored + committed at vendor/freecut/dist).
FREECUT_DIST = BASE_DIR / "vendor" / "freecut" / "dist"

# FreeCut is a File System Access API workspace editor. It is pointed at the
# project's output dir so sources, transcripts, audio/logos/stock and exports
# (written by FreeCut to projects/<id>/exports/) all live in one place.
FREECUT_WORKSPACE = OUTPUT_DIR

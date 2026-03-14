"""Django settings for tests."""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SECRET_KEY = "django_tests_secret_key"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.urls"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "OPTIONS": {
            "libraries": {
                "custom_filters": "tests.templatetags.custom_filters",
                "custom_tags": "tests.templatetags.custom_tags",
            },
        },
    },
    {
        "BACKEND": "django_templates_cythonized.backend.CythonizedTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "NAME": "cythonized",
        "OPTIONS": {
            "libraries": {
                "custom_filters": "tests.templatetags.custom_filters",
                "custom_tags": "tests.templatetags.custom_tags",
            },
        },
    },
]

USE_TZ = False

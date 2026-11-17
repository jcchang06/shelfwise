"""Django settings for Shelfwise.

One settings module for every environment: anything that differs between local,
CI and production comes from environment variables (see ../.env.example). This
avoids base/dev/prod drift and matches how Render and GitHub Actions inject config.
"""

from datetime import timedelta
from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# A local .env is optional (docker-compose passes env vars directly; CI and Render set them).
# overwrite=False: a variable already in the process environment WINS over .env, so
# `export DATABASE_URL=<neon>` points manage.py at Neon even with a local .env present.
# (django-environ uses os.environ.setdefault; proven by config/tests/test_settings_env.py.)
# DJANGO_ENV_FILE exists so that test can supply its own file.
ENV_FILE = Path(env.str("DJANGO_ENV_FILE", default=str(BASE_DIR.parent / ".env")))
environ.Env.read_env(ENV_FILE, overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS: list[str] = []

# Render sets this to the service's public hostname (e.g. shelfwise-api-et8p.onrender.com),
# so production never needs the hostname typed into an env var.
RENDER_EXTERNAL_HOSTNAME = env.str("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    # The admin login POSTs over HTTPS behind Render's proxy; Django checks the Origin.
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "corsheaders",
    # Local
    "accounts",
    "catalog",
    "tracking",
    "imports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves collectstatic output (the admin's CSS/JS) when DEBUG is off; Render has no
    # separate static file server for a Python service.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Postgres everywhere (local Docker, CI service container, Neon in production).
# conn_max_age keeps connections open between requests; health checks drop
# connections Neon closed while scaled to zero.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL"),
        conn_max_age=env.int("DB_CONN_MAX_AGE", default=60),
        conn_health_checks=True,
    )
}

# Custom user from day one: swapping AUTH_USER_MODEL after the first migration is painful.
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# The reader's time zone: "today" for default dates (started/finished/DNF) and the
# calendar for monthly stats. Timestamps are still stored in UTC (USE_TZ).
TIME_ZONE = env("TIME_ZONE", default="America/Los_Angeles")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed, content-hashed files so browsers can cache them forever.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- API -----------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Secure by default: endpoints must opt out (e.g. health, sign-up) explicitly.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Only views that set throttle_scope are throttled. "auth" covers sign-up and login,
    # which are the endpoints worth brute-forcing.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("AUTH_THROTTLE_RATE", default="10/minute"),
        # Per user. Protects the 1,000/day Google Books quota from a runaway client.
        "book_search": env("BOOK_SEARCH_THROTTLE_RATE", default="30/minute"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=7)),
    "UPDATE_LAST_LOGIN": True,
    # Each refresh also returns a new refresh token, so daily use slides the 7-day window
    # forward instead of forcing a weekly re-login. No blacklist in v1: an old refresh
    # token stays valid until it expires (see docs/implementation-notes.md, T-1).
    "ROTATE_REFRESH_TOKENS": True,
}

# v1 has one user. Set to false in production once your account exists, so strangers
# can't register on the public deployment (and spend the Google Books quota).
ALLOW_SIGNUP = env.bool("ALLOW_SIGNUP", default=True)

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])

# --- Cache --------------------------------------------------------------------

# Database cache: shared by every process and survives Render's free instance sleeping,
# unlike locmem. Holds API response caches, the Google quota flag and throttle counters.
# Needs `python manage.py createcachetable` once per database (see README).
# Tests swap in locmem (conftest.py).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# --- Integrations -------------------------------------------------------------

GOOGLE_BOOKS_API_KEY = env("GOOGLE_BOOKS_API_KEY", default="")
# ISO 639-1 code. Google Books uses it as langRestrict; Open Library as its lang ranking hint.
BOOK_SEARCH_LANGUAGE = env("BOOK_SEARCH_LANGUAGE", default="en")
# Open Library asks API clients to identify themselves.
OPEN_LIBRARY_USER_AGENT = env(
    "OPEN_LIBRARY_USER_AGENT",
    default="Shelfwise/0.1 (+https://github.com/jcchang06/shelfwise)",
)
# Open Library allows 1 request/second for clients that don't give a contact email in the
# User-Agent, 3/second for those that do. We send no email by default, so: 1. Set this to
# 3 only after adding a contact to OPEN_LIBRARY_USER_AGENT. 0 disables throttling (tests).
OPEN_LIBRARY_REQUESTS_PER_SECOND = env.float("OPEN_LIBRARY_REQUESTS_PER_SECOND", default=1.0)
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# --- Domain -------------------------------------------------------------------

# Penalty weights for DNF reasons in recommendations (R-5). Kept here, not in the
# engine, so they can be tuned without touching scoring code.
DNF_REASON_WEIGHTS = {
    "writing_style": 1.0,
    "not_my_genre": 1.0,
    "pacing": 0.5,
    "content": 0.5,
    "not_in_the_mood": 0.0,
    "other": 0.5,
}

# Upper bound on pages logged for one book on one day (T-3). Catches typos like 3000 for 30.
MAX_PAGES_PER_DAY = env.int("MAX_PAGES_PER_DAY", default=2000)

# Genre labels left out of the dashboard's genre mix (T-5), compared case-insensitively.
# Broad labels like these tag nearly every book and would dwarf the specific genres.
STATS_EXCLUDED_GENRES = env.list("STATS_EXCLUDED_GENRES", default=["Fiction", "Nonfiction"])

# Goodreads import (Phase 2). The CSV is parsed in memory and never stored.
IMPORT_MAX_FILE_BYTES = env.int("IMPORT_MAX_FILE_BYTES", default=5 * 1024 * 1024)
IMPORT_MAX_ROWS = env.int("IMPORT_MAX_ROWS", default=10_000)
# Google Books calls imports may use per day (Pacific), leaving the rest of the 1,000/day
# quota for search. When it runs out, an import pauses until the next day.
IMPORT_GOOGLE_DAILY_BUDGET = env.int("IMPORT_GOOGLE_DAILY_BUDGET", default=600)

# --- Production hardening -----------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Render terminates TLS
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    # Render health-checks over plain HTTP (Host = the onrender.com hostname). It accepts
    # 3xx too, but a direct 200 keeps the check simple to read in its logs.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start HSTS at one day; raise it once production is known-good. No subdomains or
    # preload: onrender.com is a shared domain.
    SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=86400)
    # Deliberately off for the reason above, so `check --deploy` can fail CI on anything else.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# Send errors to stdout/stderr so they show up in Render's logs. With DEBUG off, Django's
# default is to email them to ADMINS, which isn't configured.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

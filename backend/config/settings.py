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
environ.Env.read_env(BASE_DIR.parent / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
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

# --- Production hardening -----------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # Render terminates TLS
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

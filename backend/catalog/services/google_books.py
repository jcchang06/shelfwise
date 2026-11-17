"""Google Books API client: the primary search source (C-1) and metadata for saves (C-2).

Docs: https://developers.google.com/books/docs/v1/using
Free quota: 1,000 requests a day, reset at midnight Pacific time.
"""

import datetime as dt
import hashlib
import logging
from functools import cache as memoize
from typing import Any
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache

from . import normalize
from .http import build_session, get_response, parse_json
from .types import (
    AuthorRef,
    BookNotFoundError,
    BookResult,
    BookSourceError,
    QuotaExceededError,
    RateLimitedError,
    Source,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://www.googleapis.com/books/v1"
PAGE_SIZE = 20
SEARCH_CACHE_SECONDS = 24 * 60 * 60
VOLUME_CACHE_SECONDS = 7 * 24 * 60 * 60

# Lives in the shared (database) cache so every process, and later the jobs, see it.
QUOTA_FLAG_KEY = "google_books:quota_exhausted"
PACIFIC = ZoneInfo("America/Los_Angeles")


@memoize
def _session() -> requests.Session:
    return build_session()


# --- Request building (also used by scripts/record_fixtures.py) ---------------


def search_params(query: str, page: int = 1) -> dict[str, Any]:
    isbn = normalize.parse_isbn_query(query)
    params: dict[str, Any] = {
        "q": f"isbn:{isbn}" if isbn else query,
        "startIndex": (page - 1) * PAGE_SIZE,
        "maxResults": PAGE_SIZE,
        "printType": "books",  # no magazines
        "langRestrict": settings.BOOK_SEARCH_LANGUAGE,
    }
    return _with_key(params)


def volume_params() -> dict[str, Any]:
    return _with_key({})


def _with_key(params: dict[str, Any]) -> dict[str, Any]:
    # The API works without a key at a much lower shared quota, so a missing key isn't fatal.
    if settings.GOOGLE_BOOKS_API_KEY:
        params["key"] = settings.GOOGLE_BOOKS_API_KEY
    return params


# --- Quota circuit breaker ----------------------------------------------------


def seconds_until_quota_reset(now: dt.datetime) -> int:
    """Seconds from `now` until the next midnight Pacific, when Google resets the quota."""
    local = now.astimezone(PACIFIC)
    next_midnight = dt.datetime.combine(
        local.date() + dt.timedelta(days=1), dt.time.min, tzinfo=PACIFIC
    )
    return max(int((next_midnight - local).total_seconds()), 60)


def quota_exhausted() -> bool:
    return bool(cache.get(QUOTA_FLAG_KEY))


def _limit_kind(response: requests.Response) -> str | None:
    """ "daily", "rate" (short-term) or None, from a 429/403 response.

    Google answers 429 for both its per-minute and its daily limits; only the error body
    says which. Treating every 429 as daily (as this used to) blocked Google for the rest
    of the day after one burst. Only an explicit daily limit sets the all-day flag; any
    other 429 is a short-term rate limit.
    """
    if response.status_code not in (403, 429):
        return None
    try:
        error = response.json().get("error", {}) or {}
    except ValueError:
        error = {}
    reasons = " ".join(str(e.get("reason", "")) for e in error.get("errors", []) or []).lower()
    message = str(error.get("message", "")).lower()
    if "dailylimitexceeded" in reasons or "per day" in message:
        return "daily"
    if response.status_code == 429 or "ratelimitexceeded" in reasons:
        return "rate"
    if "limitexceeded" in reasons or "quotaexceeded" in reasons:  # older 403 quota forms
        return "daily"
    return None


def _get(url: str, params: dict[str, Any]) -> Any:
    if quota_exhausted():
        raise QuotaExceededError("Google Books quota exhausted until midnight Pacific")

    response = get_response(_session(), url, params)
    kind = _limit_kind(response)
    if kind == "daily":
        timeout = seconds_until_quota_reset(dt.datetime.now(tz=dt.UTC))
        cache.set(QUOTA_FLAG_KEY, True, timeout=timeout)
        logger.warning("Google Books daily quota exhausted; skipping it for %ss", timeout)
        raise QuotaExceededError("Google Books quota exhausted")
    if kind == "rate":
        logger.info("Google Books rate limit hit (short-term)")
        raise RateLimitedError("Google Books is rate limiting requests; try again shortly.")
    if response.status_code == 404:
        raise BookNotFoundError(url.rsplit("/", 1)[-1])
    if not response.ok:
        raise BookSourceError(f"Google Books returned {response.status_code}")
    return parse_json(response)


# --- Public API ---------------------------------------------------------------


def search(query: str, page: int = 1) -> list[BookResult]:
    normalized = " ".join(query.lower().split())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:32]
    cache_key = f"google_books:search:{settings.BOOK_SEARCH_LANGUAGE}:{page}:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"{API_ROOT}/volumes", search_params(query, page))
    results = [r for item in data.get("items") or () if (r := parse_volume(item))]
    cache.set(cache_key, results, timeout=SEARCH_CACHE_SECONDS)
    return results


def get_volume(volume_id: str) -> BookResult:
    cache_key = f"google_books:volume:{volume_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"{API_ROOT}/volumes/{volume_id}", volume_params())
    result = parse_volume(data)
    if result is None:
        raise BookNotFoundError(volume_id)
    cache.set(cache_key, result, timeout=VOLUME_CACHE_SECONDS)
    return result


def parse_volume(item: dict[str, Any]) -> BookResult | None:
    """One Google volume -> BookResult. Returns None if it lacks an ID or title."""
    info = item.get("volumeInfo") or {}
    volume_id, title = item.get("id"), normalize.clean_text(info.get("title"))
    if not volume_id or not title:
        return None
    identifiers = info.get("industryIdentifiers") or ()
    images = info.get("imageLinks") or {}
    return BookResult(
        source=Source.GOOGLE_BOOKS,
        source_id=volume_id,
        title=title,
        authors=tuple(
            AuthorRef(name=name)
            for name in (normalize.clean_text(a) for a in info.get("authors") or ())
            if name
        ),
        description=normalize.clean_description(info.get("description")),
        genres=normalize.genres_from_google_categories(info.get("categories")),
        page_count=info.get("pageCount") or None,
        published_date=info.get("publishedDate") or "",
        isbn_13=normalize.first_isbn_13(
            (i.get("identifier", "") for i in identifiers if i.get("type") == "ISBN_13"),
            settings.BOOK_SEARCH_LANGUAGE,
        ),
        cover_url=normalize.https_cover_url(
            images.get("thumbnail") or images.get("smallThumbnail")
        ),
    )

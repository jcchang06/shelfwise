"""Open Library API client: fallback search source (C-1) and metadata for saves (C-2).

Docs: https://openlibrary.org/dev/docs/api/search and https://openlibrary.org/dev/docs/api/books
No key. Open Library asks clients to send an identifying User-Agent (settings).
"""

import hashlib
from functools import cache as memoize
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

from . import normalize
from .http import build_session, get_response, parse_json
from .types import AuthorRef, BookNotFoundError, BookResult, BookSourceError, Source

API_ROOT = "https://openlibrary.org"
COVERS_ROOT = "https://covers.openlibrary.org/b/id"
PAGE_SIZE = 20
SEARCH_CACHE_SECONDS = 24 * 60 * 60
WORK_CACHE_SECONDS = 7 * 24 * 60 * 60

# Only the fields we map, which keeps responses small.
SEARCH_FIELDS = ",".join(
    [
        "key",
        "title",
        "author_name",
        "author_key",
        "first_publish_year",
        "number_of_pages_median",
        "isbn",
        "subject",
        "cover_i",
    ]
)


@memoize
def _session() -> requests.Session:
    return build_session()


# --- Request building (also used by scripts/record_fixtures.py) ---------------


def search_params(query: str, page: int = 1) -> dict[str, Any]:
    isbn = normalize.parse_isbn_query(query)
    return {
        "q": f"isbn:{isbn}" if isbn else query,
        "page": page,
        "limit": PAGE_SIZE,
        "fields": SEARCH_FIELDS,
        "lang": settings.BOOK_SEARCH_LANGUAGE,  # a ranking hint, not a filter
    }


def work_search_params(work_key: str) -> dict[str, Any]:
    """Search for exactly one work: the work JSON lacks author names, ISBNs and page counts."""
    return {"q": f"key:/works/{work_key}", "limit": 1, "fields": SEARCH_FIELDS}


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    response = get_response(_session(), url, params)
    if response.status_code == 404:
        raise BookNotFoundError(url.rsplit("/", 1)[-1])
    if not response.ok:
        raise BookSourceError(f"Open Library returned {response.status_code}")
    return parse_json(response)


# --- Public API ---------------------------------------------------------------


def search(query: str, page: int = 1) -> list[BookResult]:
    normalized = " ".join(query.lower().split())
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:32]
    cache_key = f"open_library:search:{settings.BOOK_SEARCH_LANGUAGE}:{page}:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"{API_ROOT}/search.json", search_params(query, page))
    results = [r for doc in data.get("docs") or () if (r := parse_search_doc(doc))]
    cache.set(cache_key, results, timeout=SEARCH_CACHE_SECONDS)
    return results


def get_work(work_key: str) -> BookResult:
    """Full record for one work: the search doc merged with the work's description."""
    cache_key = f"open_library:work:{work_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    work = _get(f"{API_ROOT}/works/{work_key}.json")
    docs = _get(f"{API_ROOT}/search.json", work_search_params(work_key)).get("docs") or ()
    doc = next((d for d in docs if _work_key(d.get("key")) == work_key), None)

    base = parse_search_doc(doc) if doc else None
    result = merge_work(base, work, work_key)
    if result is None:
        raise BookNotFoundError(work_key)
    cache.set(cache_key, result, timeout=WORK_CACHE_SECONDS)
    return result


# --- Parsing ------------------------------------------------------------------


def _work_key(key: str | None) -> str:
    """ "/works/OL82563W" -> "OL82563W"."""
    return (key or "").rsplit("/", 1)[-1]


def _cover_url(cover_id: int | None) -> str:
    return f"{COVERS_ROOT}/{cover_id}-L.jpg" if cover_id else ""


def parse_search_doc(doc: dict[str, Any]) -> BookResult | None:
    key, title = _work_key(doc.get("key")), normalize.clean_text(doc.get("title"))
    if not key or not title:
        return None
    names = doc.get("author_name") or ()
    keys = doc.get("author_key") or ()
    authors = tuple(
        AuthorRef(name=clean, open_library_key=keys[i] if i < len(keys) else None)
        for i, name in enumerate(names)
        if (clean := normalize.clean_text(name))
    )
    year = doc.get("first_publish_year")
    return BookResult(
        source=Source.OPEN_LIBRARY,
        source_id=key,
        title=title,
        authors=authors,
        genres=normalize.genres_from_open_library_subjects(doc.get("subject")),
        page_count=doc.get("number_of_pages_median") or None,
        published_date=str(year) if year else "",
        isbn_13=normalize.first_isbn_13(doc.get("isbn"), settings.BOOK_SEARCH_LANGUAGE),
        cover_url=_cover_url(doc.get("cover_i")),
    )


def _description(work: dict[str, Any]) -> str:
    # Either a plain string or {"type": "/type/text", "value": "..."}.
    raw = work.get("description")
    if isinstance(raw, dict):
        raw = raw.get("value")
    return normalize.clean_description(raw if isinstance(raw, str) else None)


def merge_work(base: BookResult | None, work: dict[str, Any], work_key: str) -> BookResult | None:
    """Add the work's description (and subjects/cover when the search doc had none)."""
    if base is None:
        title = normalize.clean_text(work.get("title"))
        if not title:
            return None
        base = BookResult(source=Source.OPEN_LIBRARY, source_id=work_key, title=title)
    covers = [c for c in work.get("covers") or () if isinstance(c, int) and c > 0]
    return BookResult(
        source=base.source,
        source_id=base.source_id,
        title=base.title,
        authors=base.authors,
        description=_description(work) or base.description,
        genres=base.genres or normalize.genres_from_open_library_subjects(work.get("subjects")),
        page_count=base.page_count,
        published_date=base.published_date,
        isbn_13=base.isbn_13,
        cover_url=base.cover_url or _cover_url(covers[0] if covers else None),
    )

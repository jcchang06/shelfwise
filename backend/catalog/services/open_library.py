"""Open Library API client: fallback search source (C-1) and metadata for saves (C-2).

Docs: https://openlibrary.org/dev/docs/api/search and https://openlibrary.org/dev/docs/api/books
No key. Open Library asks clients to send an identifying User-Agent (settings).
"""

import hashlib
import threading
import time
from dataclasses import replace
from functools import cache as memoize
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

from . import normalize
from .http import build_session, get_response, parse_json
from .types import (
    AuthorCandidate,
    AuthorRef,
    AuthorWork,
    BookNotFoundError,
    BookResult,
    BookSourceError,
    Source,
)

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


_throttle_lock = threading.Lock()
_last_request_at = 0.0


def _throttle() -> None:
    """Space requests to OPEN_LIBRARY_REQUESTS_PER_SECOND (their published limit), across
    all callers in this process. Search, saves and imports all go through here."""
    global _last_request_at
    rate = settings.OPEN_LIBRARY_REQUESTS_PER_SECOND
    if rate <= 0:
        return
    with _throttle_lock:
        wait = _last_request_at + 1 / rate - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    _throttle()
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


# --- Batch ISBN lookup (Goodreads import) ---------------------------------------------

# ISBNs per search request. Open Library asks for batched search.json queries rather than
# "hundreds of single-book requests"; this keeps the query string comfortably short.
ISBN_BATCH_SIZE = 40


def isbn_batch_params(isbns: list[str]) -> dict[str, Any]:
    return {
        "q": f"isbn:({' OR '.join(isbns)})",
        "fields": SEARCH_FIELDS,
        # One ISBN can belong to several works, so allow a few results per ISBN.
        "limit": len(isbns) * 3,
    }


def search_by_isbns(isbns: list[str]) -> dict[str, list[BookResult]]:
    """{isbn: [results whose editions include it]} for many ISBNs, ISBN_BATCH_SIZE per
    request. Each result's isbn_13 is set to the ISBN that matched, so the saved book
    gets the edition the reader actually has. Missing ISBNs are simply absent."""
    wanted = list(dict.fromkeys(i for i in isbns if i))
    found: dict[str, list[BookResult]] = {}
    for start in range(0, len(wanted), ISBN_BATCH_SIZE):
        chunk = wanted[start : start + ISBN_BATCH_SIZE]
        docs = _get(f"{API_ROOT}/search.json", isbn_batch_params(chunk)).get("docs") or ()
        for doc in docs:
            result = parse_search_doc(doc)
            if result is None:
                continue
            # Some editions are listed only by ISBN-10; compare everything as ISBN-13.
            doc_isbns = {normalize.as_isbn_13(i) for i in doc.get("isbn") or ()}
            for isbn in chunk:
                if isbn in doc_isbns:
                    found.setdefault(isbn, []).append(replace(result, isbn_13=isbn))
    return found


def title_author_params(title: str, author: str) -> dict[str, Any]:
    return {"title": title, "author": author, "fields": SEARCH_FIELDS, "limit": 10}


def search_title_author(title: str, author: str) -> list[BookResult]:
    """Search by title and author fields (one throttled search.json request, cached)."""
    key = hashlib.sha256(f"{title.lower()}|{author.lower()}".encode()).hexdigest()[:32]
    cache_key = f"open_library:title_author:{key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    docs = _get(f"{API_ROOT}/search.json", title_author_params(title, author)).get("docs") or ()
    results = [r for doc in docs if (r := parse_search_doc(doc))]
    cache.set(cache_key, results, timeout=SEARCH_CACHE_SECONDS)
    return results


# --- Authors (C-5 author pages; reused by the N-2 release check) ----------------------

AUTHOR_CACHE_SECONDS = 24 * 60 * 60
AUTHOR_WORKS_LIMIT = 100
AUTHOR_WORK_FIELDS = "key,title,first_publish_year,cover_i,edition_count,language"
# Open Library tags editions with MARC language codes.
_MARC_LANGUAGE = {"en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita", "pt": "por"}


def author_works_params(author_key: str, sort: str) -> dict[str, Any]:
    return {
        "q": f"author_key:{author_key}",
        "fields": AUTHOR_WORK_FIELDS,
        "sort": sort,  # "new" (first published, newest first) or "editions"
        "limit": AUTHOR_WORKS_LIMIT,
    }


def author_works(author_key: str, sort: str = "new") -> list[AuthorWork]:
    """Up to AUTHOR_WORKS_LIMIT works by one author, in BOOK_SEARCH_LANGUAGE or with no
    language listed, one per title (the one with the most editions), oldest first.

    sort="new" guarantees the newest works are included (the release check); "editions"
    the best-known ones (an author page, where a prolific author's classics matter).
    Cached for a day. One throttled request.
    """
    cache_key = f"open_library:author_works:{sort}:{author_key}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    docs = _get(f"{API_ROOT}/search.json", author_works_params(author_key, sort)).get("docs")
    works = parse_author_works(docs or (), settings.BOOK_SEARCH_LANGUAGE)
    cache.set(cache_key, works, timeout=AUTHOR_CACHE_SECONDS)
    return works


def parse_author_works(docs: Any, language: str) -> list[AuthorWork]:
    wanted = _MARC_LANGUAGE.get(language)
    best: dict[str, AuthorWork] = {}
    for doc in docs:
        key, title = _work_key(doc.get("key")), normalize.clean_text(doc.get("title"))
        languages = doc.get("language") or ()
        if not key or not title or (wanted and languages and wanted not in languages):
            continue
        work = AuthorWork(
            work_key=key,
            title=title,
            first_publish_year=doc.get("first_publish_year") or None,
            cover_url=_cover_url(doc.get("cover_i")),
            edition_count=doc.get("edition_count") or 0,
        )
        # Open Library lists re-releases as separate works; keep the best-known one.
        name = normalize.normalize_title(title) or title.casefold()
        if name not in best or work.edition_count > best[name].edition_count:
            best[name] = work
    return sorted(best.values(), key=lambda w: (w.first_publish_year or 9999, w.title))


def search_authors(name: str) -> list[AuthorCandidate]:
    """Open Library authors matching a name (one throttled request, cached for a day)."""
    digest = hashlib.sha256(name.casefold().encode()).hexdigest()[:32]
    cache_key = f"open_library:search_authors:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    docs = _get(f"{API_ROOT}/search/authors.json", {"q": name, "limit": 5}).get("docs") or ()
    found = [
        AuthorCandidate(
            key=_work_key(doc.get("key")),
            name=normalize.clean_text(doc.get("name")),
            alternate_names=tuple(n for n in doc.get("alternate_names") or () if n),
            work_count=doc.get("work_count") or 0,
        )
        for doc in docs
        if doc.get("key") and doc.get("name")
    ]
    cache.set(cache_key, found, timeout=AUTHOR_CACHE_SECONDS)
    return found


# --- Work details in batches (C-3 catalog seed) -----------------------------------------

WORK_BATCH_SIZE = 100
WORK_DETAIL_FIELDS = "key,first_publish_year,number_of_pages_median,isbn,language"


def work_details_params(work_keys: list[str]) -> dict[str, Any]:
    keys = " OR ".join(f"/works/{key}" for key in work_keys)
    return {"q": f"key:({keys})", "fields": WORK_DETAIL_FIELDS, "limit": len(work_keys)}


def work_details(work_keys: list[str]) -> dict[str, dict[str, Any]]:
    """{work key: {first_publish_year, page_count, isbn_13, languages}} for up to
    WORK_BATCH_SIZE works in one throttled search request (what the 12.6 GB editions
    dump would otherwise provide). Works Open Library doesn't return are absent."""
    if len(work_keys) > WORK_BATCH_SIZE:
        raise ValueError(f"At most {WORK_BATCH_SIZE} work keys per request")
    docs = _get(f"{API_ROOT}/search.json", work_details_params(work_keys)).get("docs") or ()
    found: dict[str, dict[str, Any]] = {}
    for doc in docs:
        key = _work_key(doc.get("key"))
        if not key:
            continue
        found[key] = {
            "first_publish_year": doc.get("first_publish_year") or None,
            "page_count": doc.get("number_of_pages_median") or None,
            "isbn_13": normalize.first_isbn_13(doc.get("isbn"), settings.BOOK_SEARCH_LANGUAGE),
            "languages": tuple(doc.get("language") or ()),
        }
    return found


def marc_language(language: str) -> str | None:
    """ "en" -> "eng": Open Library tags editions with MARC language codes."""
    return _MARC_LANGUAGE.get(language)


RECENT_PAGE_SIZE = 1000  # Open Library's maximum `limit`


def popular_recent_work_keys(from_year: int, to_year: int, count: int) -> dict[str, int]:
    """{work key: readers} for the `count` most-read works first published in
    from_year..to_year with an edition in BOOK_SEARCH_LANGUAGE, most read first. The
    dumps' reading log is too thin on new books for a top-N cut to find enough of them.
    One throttled request per RECENT_PAGE_SIZE works."""
    language = marc_language(settings.BOOK_SEARCH_LANGUAGE)
    query = f"first_publish_year:[{from_year} TO {to_year}]"
    if language:
        query += f" language:{language}"
    found: dict[str, int] = {}
    page = 1
    while len(found) < count:
        params = {
            "q": query,
            "sort": "readinglog",
            "fields": "key,readinglog_count",
            "limit": min(RECENT_PAGE_SIZE, count - len(found)),
            "page": page,
        }
        docs = _get(f"{API_ROOT}/search.json", params).get("docs") or ()
        for doc in docs:
            if key := _work_key(doc.get("key")):
                found.setdefault(key, doc.get("readinglog_count") or 0)
        if len(docs) < params["limit"]:
            break
        page += 1
    return found

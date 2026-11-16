"""Record real Google Books and Open Library responses as test fixtures.

Run once (and again whenever the API shapes need refreshing), from backend/:

    GOOGLE_BOOKS_API_KEY=... .venv/bin/python scripts/record_fixtures.py

What it writes:
- catalog/tests/fixtures/raw/*.json  full responses with the request URL. The API key is
  stripped from URLs and scrubbed from bodies. Gitignored: never commit these.
- catalog/tests/fixtures/*.json      trimmed bodies (a few results, only the fields the
  parsers read). These are committed and used by the tests.

It reuses the services' own *_params() builders, so recorded requests match what the
app sends.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import django
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402

from catalog.services import google_books, open_library  # noqa: E402

FIXTURES_DIR = BACKEND_DIR / "catalog" / "tests" / "fixtures"
RAW_DIR = FIXTURES_DIR / "raw"

SEARCH_QUERY = "project hail mary"
ISBN_QUERY = "9780593135204"  # Project Hail Mary, first US hardcover
EMPTY_QUERY = "qzxqv nonexistent shelfwise fixture"
KEEP_RESULTS = 3
KEEP_LIST_ITEMS = 15  # subjects, ISBNs

GOOGLE_INFO_FIELDS = (
    "title",
    "subtitle",
    "authors",
    "publishedDate",
    "description",
    "industryIdentifiers",
    "pageCount",
    "categories",
    "imageLinks",
    "language",
)
WORK_FIELDS = ("key", "title", "description", "subjects", "covers", "authors")


def fetch(url: str, params: dict[str, Any]) -> tuple[str, int, Any]:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": settings.OPEN_LIBRARY_USER_AGENT},
        timeout=(5, 15),
    )
    public_params = {k: v for k, v in params.items() if k != "key"}
    public_url = requests.Request("GET", url, params=public_params).prepare().url or url
    return public_url, response.status_code, response.json()


def scrub(text: str) -> str:
    key = settings.GOOGLE_BOOKS_API_KEY
    return text.replace(key, "REDACTED") if key else text


def write(name: str, data: Any, raw: bool) -> None:
    directory = RAW_DIR if raw else FIXTURES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(scrub(json.dumps(data, indent=2, ensure_ascii=False)) + "\n")
    print(f"  wrote {path.relative_to(BACKEND_DIR)}")


def trim_volume(item: dict[str, Any]) -> dict[str, Any]:
    info = item.get("volumeInfo", {})
    return {
        "id": item.get("id"),
        "volumeInfo": {k: info[k] for k in GOOGLE_INFO_FIELDS if k in info},
    }


def trim_google_search(body: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {"totalItems": body.get("totalItems", 0)}
    if body.get("items"):
        trimmed["items"] = [trim_volume(i) for i in body["items"][:KEEP_RESULTS]]
    return trimmed


def trim_ol_doc(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    for key in ("subject", "isbn"):
        if key in doc:
            doc[key] = doc[key][:KEEP_LIST_ITEMS]
    return doc


def trim_ol_search(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "numFound": body.get("numFound", 0),
        "docs": [trim_ol_doc(d) for d in body.get("docs", [])[:KEEP_RESULTS]],
    }


def trim_work(body: dict[str, Any]) -> dict[str, Any]:
    work = {k: body[k] for k in WORK_FIELDS if k in body}
    for key in ("subjects", "covers"):
        if key in work:
            work[key] = work[key][:KEEP_LIST_ITEMS]
    return work


def record(name: str, url: str, params: dict[str, Any], trim) -> Any:
    public_url, status, body = fetch(url, params)
    print(f"{name}: {status} {public_url}")
    if status != 200:
        sys.exit(f"Unexpected status {status} for {name}; nothing more recorded.")
    write(name, {"url": public_url, "status": status, "body": body}, raw=True)
    write(name, trim(body), raw=False)
    return body


def main() -> None:
    if not settings.GOOGLE_BOOKS_API_KEY:
        sys.exit("Set GOOGLE_BOOKS_API_KEY first (it is never written to disk).")

    gb = google_books.API_ROOT
    search = record(
        "google_search",
        f"{gb}/volumes",
        google_books.search_params(SEARCH_QUERY),
        trim_google_search,
    )
    record(
        "google_search_isbn",
        f"{gb}/volumes",
        google_books.search_params(ISBN_QUERY),
        trim_google_search,
    )
    record(
        "google_search_empty",
        f"{gb}/volumes",
        google_books.search_params(EMPTY_QUERY),
        trim_google_search,
    )
    volume_id = search["items"][0]["id"]
    record(
        "google_volume",
        f"{gb}/volumes/{volume_id}",
        google_books.volume_params(),
        trim_volume,
    )

    ol = open_library.API_ROOT
    ol_search = record(
        "ol_search", f"{ol}/search.json", open_library.search_params(SEARCH_QUERY), trim_ol_search
    )
    record(
        "ol_search_empty",
        f"{ol}/search.json",
        open_library.search_params(EMPTY_QUERY),
        trim_ol_search,
    )
    work_key = ol_search["docs"][0]["key"].rsplit("/", 1)[-1]
    record("ol_work", f"{ol}/works/{work_key}.json", {}, trim_work)
    record(
        "ol_work_search",
        f"{ol}/search.json",
        open_library.work_search_params(work_key),
        trim_ol_search,
    )
    print("\nDone. Review the trimmed fixtures, then commit them (not raw/).")


if __name__ == "__main__":
    main()

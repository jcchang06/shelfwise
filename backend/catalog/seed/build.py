"""Choosing the catalog seed (C-3) from Open Library dumps.

1. Popularity: readers per work from the reading-log dump (Want to Read, Currently
   Reading, Already Read; not Stopped Reading), ratings count as the tie-breaker.
2. Candidates: the `candidates` most popular works not already in the catalog, plus the
   RECENT_CANDIDATES most-read recent works from the search API (new books have too few
   reading-log entries in the dump to make a top-N cut; checked on the 2026-10-31 dump,
   where only 183 of the top 60,000 were eligible and recent).
3. Works dump: title, description, subjects -> genres, authors, cover. A work stays only
   with a description of MIN_DESCRIPTION_CHARS+ (after cleanup), 1+ genre and 1+ author.
4. Authors dump: the names of those works' authors.
5. Search API, WORK_BATCH_SIZE works per request: first publish year, page count,
   ISBN-13 and languages. Only works with an edition in BOOK_SEARCH_LANGUAGE stay.
6. Duplicates: skip works matching a catalog book by ISBN-13 or by normalized title +
   first author (merge_duplicate_books' rule); within the seed, keep the most popular.
7. Pools, in this order, each taking the most popular eligible works left:
   - recent (RECENT_SHARE): first published this year or in the two before it
   - taste (TASTE_SHARE): sharing a genre with the reader's finished and reading books
     (not DNF; rated 3+ or unrated), see taste_genres()
   - popular: the rest of the target
   A pool that runs short leaves its share to "popular"; the report says so.
"""

import datetime as dt
import gzip
import json
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import Q

from catalog.models import Book
from catalog.services import normalize, open_library
from catalog.services.types import BookSourceError
from tracking.models import UserBook

from . import dumps

MIN_DESCRIPTION_CHARS = 200
RECENT_SHARE = 0.10
RECENT_YEARS = 3  # this year and the two before it
RECENT_CANDIDATES = 15_000
TASTE_SHARE = 0.30
TASTE_GENRES = 10  # the reader's most common genres
RETRY_DELAYS = (5, 15)  # seconds before the 2nd and 3rd attempt of a search batch

Status = UserBook.Status


@dataclass
class SeedBook:
    work_key: str
    title: str
    authors: list[dict[str, str]]  # [{key, name}] in credit order
    description: str
    genres: list[str]
    cover_url: str = ""
    first_publish_year: int | None = None
    page_count: int | None = None
    isbn_13: str = ""
    popularity: int = 0  # readers in the reading log
    ratings: int = 0
    pool: str = ""  # recent | taste | popular

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BuildReport:
    reading_log_works: int = 0
    candidates: int = 0
    recent_candidates: int = 0  # added from the search API's recent list
    already_in_catalog: int = 0
    not_in_works_dump: int = 0
    short_description: int = 0
    no_genres: int = 0
    no_author: int = 0
    not_in_search: int = 0
    other_language: int = 0
    duplicate_of_catalog: int = 0
    duplicate_in_seed: int = 0
    eligible: int = 0
    target: int = 0
    taste_genres: int = 0
    recent_from_year: int = 0
    pools: Counter[str] = field(default_factory=Counter)
    shortfalls: dict[str, int] = field(default_factory=dict)  # pool -> books it lacked


# --- Cleanup ------------------------------------------------------------------------

_SEPARATOR = re.compile(r"^\s*\\?-{3,}\s*$", re.MULTILINE)  # before "Also contained in:"
# Lists of other works ("Contains:", "Also contained in:") start a trailing section too,
# sometimes without a separator line before them.
_WORK_LIST = re.compile(r"^\s*(contains|also contained in)\s*:", re.MULTILINE | re.IGNORECASE)
_ESCAPED_RULE = re.compile(r"\\-{3,}")  # "\---------" mid-line, a Markdown-escaped divider
# Link text may itself hold brackets: "[Deception Point [1/2]](https://…)".
_MD_INLINE_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)]*\)")
_MD_REF_LINK = re.compile(r"\[([^\]]*)\]\[\d*\]")
_MD_REF_DEFINITION = re.compile(r"^\s*\[\d+\]:\s*\S+.*$", re.MULTILINE)
_SOURCE_NOTE = re.compile(r"\(\s*(source|from)\s*\)", re.IGNORECASE)
_MD_EMPHASIS = re.compile(r"(\*\*|__|^#+\s*)", re.MULTILINE)


def clean_seed_description(raw: Any) -> str:
    """Open Library work descriptions are Markdown: drop the trailing link section, keep
    link text, then the usual HTML-to-text cleanup."""
    if isinstance(raw, dict):
        raw = raw.get("value")
    if not isinstance(raw, str):
        return ""
    text = _SEPARATOR.split(raw, maxsplit=1)[0]
    text = _WORK_LIST.split(text, maxsplit=1)[0]
    text = _ESCAPED_RULE.sub(" ", text)
    text = _MD_REF_DEFINITION.sub("", text)
    text = _MD_INLINE_LINK.sub(r"\1", text)
    text = _MD_REF_LINK.sub(r"\1", text)
    text = _SOURCE_NOTE.sub("", text)
    text = _MD_EMPHASIS.sub("", text)
    return normalize.clean_description(text)


# --- The reader's genres ----------------------------------------------------------------


def taste_genres(limit: int = TASTE_GENRES) -> list[str]:
    """The most common genres (casefolded) on finished and reading shelf entries, rated
    3+ or unrated, never DNF; minus STATS_EXCLUDED_GENRES, which match nearly anything."""
    excluded = {g.casefold() for g in settings.STATS_EXCLUDED_GENRES}
    entries = UserBook.objects.filter(status__in=[Status.FINISHED, Status.READING]).filter(
        Q(rating__isnull=True) | Q(rating__gte=3)
    )
    counts: Counter[str] = Counter()
    for genres in entries.values_list("book__genres", flat=True):
        counts.update({g.casefold() for g in genres or ()} - excluded)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))  # ties: A-Z
    return [genre for genre, _ in ranked[:limit]]


# --- Building -------------------------------------------------------------------------


def _catalog_index() -> tuple[set[str], set[str], set[tuple[str, str]]]:
    keys, isbns, names = set(), set(), set()
    for book in Book.objects.prefetch_related("book_authors__author"):
        if book.open_library_key:
            keys.add(book.open_library_key)
        if book.isbn_13:
            isbns.add(book.isbn_13)
        names.add(_name_key(book.title, _first_author(book)))
    return keys, isbns, names


def _first_author(book: Book) -> str:
    links = sorted(book.book_authors.all(), key=lambda link: link.position)
    return links[0].author.name if links else ""


def _name_key(title: str, author: str) -> tuple[str, str]:
    return normalize.normalize_title(title), normalize.normalize_author_name(author)


def parse_work(key: str, record: dict[str, Any], report: BuildReport) -> SeedBook | None:
    title = normalize.clean_text(record.get("title"))
    description = clean_seed_description(record.get("description"))
    if not title or len(description) < MIN_DESCRIPTION_CHARS:
        report.short_description += 1
        return None
    genres = list(normalize.genres_from_open_library_subjects(record.get("subjects")))
    if not genres:
        report.no_genres += 1
        return None
    author_keys = [
        k
        for entry in record.get("authors") or ()
        if isinstance(entry, dict)
        and (k := ((entry.get("author") or {}).get("key") or "").rsplit("/", 1)[-1])
    ]
    if not author_keys:
        report.no_author += 1
        return None
    covers = [c for c in record.get("covers") or () if isinstance(c, int) and c > 0]
    return SeedBook(
        work_key=key,
        title=title,
        authors=[{"key": k, "name": ""} for k in dict.fromkeys(author_keys)],
        description=description,
        genres=genres,
        cover_url=f"{open_library.COVERS_ROOT}/{covers[0]}-L.jpg" if covers else "",
    )


def _with_retries(sleep: Callable[[float], None], fetch: Callable[..., dict], *args) -> dict:
    for delay in (*RETRY_DELAYS, None):
        try:
            return fetch(*args)
        except BookSourceError:
            if delay is None:
                raise
            sleep(delay)
    raise AssertionError("unreachable")


def build_seed(
    dumps_dir: Path,
    target: int,
    candidates: int,
    genres: list[str],
    this_year: int | None = None,
    fetch_details: Callable[[list[str]], dict] | None = None,
    fetch_recent: Callable[[int, int, int], dict[str, int]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = lambda message: None,
) -> tuple[list[SeedBook], BuildReport]:
    """Choose up to `target` works. Raises dumps.DumpError for missing dumps and
    BookSourceError if Open Library search still fails after retries."""
    this_year = this_year or dt.date.today().year
    fetch_details = fetch_details or open_library.work_details
    fetch_recent = fetch_recent or open_library.popular_recent_work_keys
    report = BuildReport(target=target, taste_genres=len(genres))
    report.recent_from_year = this_year - RECENT_YEARS + 1

    progress("Counting readers per work (reading log)…")
    readers = dumps.reading_log_counts(dumps.find_dump(dumps_dir, "reading-log"))
    report.reading_log_works = len(readers)
    try:
        ratings = dumps.rating_counts(dumps.find_dump(dumps_dir, "ratings"))
    except dumps.DumpError:
        ratings = Counter()

    catalog_keys, catalog_isbns, catalog_names = _catalog_index()
    ranked = sorted(readers, key=lambda w: (-readers[w], -ratings[w], w))
    wanted: list[int] = []
    for work in ranked:
        if dumps.work_key(work) in catalog_keys:
            report.already_in_catalog += 1
            continue
        wanted.append(work)
        if len(wanted) >= candidates:
            break

    progress("Listing the most-read recent works (search API)…")
    recent_readers = _with_retries(
        sleep, fetch_recent, report.recent_from_year, this_year, RECENT_CANDIDATES
    )
    already = set(wanted)
    extra = 0
    for key, count in recent_readers.items():
        work = dumps.key_id(key)
        if work is None or work in already or key in catalog_keys:
            continue
        already.add(work)
        # Rank new books by the search's reader count when the dump has none for them.
        readers[work] = max(readers[work], count)
        wanted.append(work)
        extra += 1
    report.recent_candidates = extra
    report.candidates = len(wanted)

    progress(f"Reading {len(wanted)} candidate works from the works dump…")
    books: dict[str, SeedBook] = {}
    for work, record in dumps.records(dumps.find_dump(dumps_dir, "works"), set(wanted), "W"):
        key = dumps.work_key(work)
        if book := parse_work(key, record, report):
            book.popularity, book.ratings = readers[work], ratings[work]
            books[key] = book
    report.not_in_works_dump = (
        len(wanted) - len(books) - (report.short_description + report.no_genres + report.no_author)
    )

    progress(f"Reading author names for {len(books)} works…")
    author_ids = {
        a_id for b in books.values() for a in b.authors if (a_id := dumps.key_id(a["key"], "A"))
    }
    names: dict[str, str] = {}
    for author_id, record in dumps.records(dumps.find_dump(dumps_dir, "authors"), author_ids, "A"):
        if name := normalize.clean_text(record.get("name")):
            names[f"OL{author_id}A"] = name
    for book in list(books.values()):
        book.authors = [
            {"key": a["key"], "name": names[a["key"]]} for a in book.authors if a["key"] in names
        ]
        if not book.authors:
            report.no_author += 1
            del books[book.work_key]

    progress(f"Looking up years, pages and languages for {len(books)} works (search API)…")
    language = open_library.marc_language(settings.BOOK_SEARCH_LANGUAGE)
    keys = list(books)
    for start in range(0, len(keys), open_library.WORK_BATCH_SIZE):
        batch = keys[start : start + open_library.WORK_BATCH_SIZE]
        details = _with_retries(sleep, fetch_details, batch)
        for key in batch:
            info = details.get(key)
            if info is None:
                report.not_in_search += 1
                del books[key]
            elif language and language not in info["languages"]:
                report.other_language += 1
                del books[key]
            else:
                book = books[key]
                book.first_publish_year = info["first_publish_year"]
                book.page_count = info["page_count"]
                book.isbn_13 = info["isbn_13"]

    eligible = _dedupe(
        sorted(books.values(), key=lambda b: (-b.popularity, -b.ratings, b.work_key)),
        catalog_isbns,
        catalog_names,
        report,
    )
    report.eligible = len(eligible)
    chosen = select(eligible, target, genres, report.recent_from_year, report)
    return chosen, report


def _dedupe(ranked, catalog_isbns, catalog_names, report) -> list[SeedBook]:
    kept, seen = [], set()
    for book in ranked:
        name = _name_key(book.title, book.authors[0]["name"])
        if (book.isbn_13 and book.isbn_13 in catalog_isbns) or name in catalog_names:
            report.duplicate_of_catalog += 1
        elif name in seen:
            report.duplicate_in_seed += 1  # a less popular copy of a work already kept
        else:
            seen.add(name)
            kept.append(book)
    return kept


def select(
    ranked: list[SeedBook], target: int, genres: list[str], recent_from: int, report: BuildReport
) -> list[SeedBook]:
    """Fill the pools from `ranked` (most popular first). See the module docstring."""
    taste = set(genres)
    quotas = {"recent": round(target * RECENT_SHARE), "taste": round(target * TASTE_SHARE)}
    rules = {
        "recent": lambda b: (b.first_publish_year or 0) >= recent_from,
        "taste": lambda b: any(g.casefold() in taste for g in b.genres),
    }
    chosen: list[SeedBook] = []
    used: set[str] = set()
    for pool, quota in quotas.items():
        picked = [b for b in ranked if b.work_key not in used and rules[pool](b)][:quota]
        for book in picked:
            book.pool = pool
            used.add(book.work_key)
        chosen += picked
        if len(picked) < quota:
            report.shortfalls[pool] = quota - len(picked)
    for book in ranked:
        if len(chosen) >= target:
            break
        if book.work_key not in used:
            book.pool = "popular"
            used.add(book.work_key)
            chosen.append(book)
    if len(chosen) < target:
        report.shortfalls["total"] = target - len(chosen)
    report.pools = Counter(book.pool for book in chosen)
    return chosen


def write_seed(path: Path, books: list[SeedBook]) -> None:
    """One JSON object per line, gzipped."""
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for book in books:
            handle.write(json.dumps(book.as_record(), ensure_ascii=False) + "\n")

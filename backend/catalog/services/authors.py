"""Author pages (C-5): an author's Open Library bibliography merged with the catalog.

resolve_author_key() finds the author's Open Library key, without guessing between
namesakes:

1. The key the author already has (the import and the C-6 nightly job fill these).
2. The works of this author's catalog books (open_library.get_work, cached): the author
   listed there under the same normalized name. This also finds a key held by another
   author row, the same person under another spelling (author rows aren't merged).
3. Open Library's author search, accepting a namesake only if their works include one of
   this author's catalog books (by work key or title). Otherwise: no key.

A key found in step 2 or 3 is saved on the author unless another author row has it.

author_works_for() merges the "editions" and "new" bibliographies (a prolific author's
classics and newest releases), matches works to catalog books by work key, then title,
and adds the author's catalog books Open Library doesn't list.
"""

import logging
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from catalog.models import Author, Book

from . import normalize, open_library
from .catalog import _normalized_author_name  # same database normalization
from .types import AuthorRef, AuthorWork, BookNotFoundError, BookResult

logger = logging.getLogger(__name__)

# Catalog books whose works are checked for the author's key, and namesakes tried.
MAX_BOOKS_TO_CHECK = 3
MAX_CANDIDATES = 3


def _author_books(author: Author) -> list[Book]:
    return list(author.books.order_by("created_at", "id"))


def _same_name(a: str, b: str) -> bool:
    return normalize.normalize_author_name(a) == normalize.normalize_author_name(b)


def resolve_author_key(author: Author) -> str | None:
    """The author's Open Library key, or None. Raises BookSourceError if Open Library
    can't be reached (the page then shows catalog books only)."""
    if author.open_library_key:
        return author.open_library_key
    books = _author_books(author)
    key = _key_from_catalog_works(author, books) or _key_from_author_search(author, books)
    if key:
        _save_key(author, key)
    return key


def _key_from_catalog_works(author: Author, books: list[Book]) -> str | None:
    for book in [b for b in books if b.open_library_key][:MAX_BOOKS_TO_CHECK]:
        try:
            work = open_library.get_work(book.open_library_key)
        except BookNotFoundError:
            continue
        for ref in work.authors:
            if ref.open_library_key and _same_name(ref.name, author.name):
                return ref.open_library_key
    return None


def _key_from_author_search(author: Author, books: list[Book]) -> str | None:
    if not books:
        return None  # nothing to confirm a namesake against
    keys = {b.open_library_key for b in books if b.open_library_key}
    titles = {normalize.normalize_title(b.title) for b in books} - {""}
    candidates = [
        c
        for c in open_library.search_authors(author.name)
        if any(_same_name(n, author.name) for n in (c.name, *c.alternate_names))
    ]
    candidates.sort(key=lambda c: -c.work_count)
    for candidate in candidates[:MAX_CANDIDATES]:
        works = open_library.author_works(candidate.key, sort="editions")
        if any(w.work_key in keys or normalize.normalize_title(w.title) in titles for w in works):
            return candidate.key
    return None


def _save_key(author: Author, key: str) -> None:
    if Author.objects.filter(open_library_key=key).exclude(pk=author.pk).exists():
        return  # the same person under another spelling: use the key, don't copy it
    try:
        Author.objects.filter(pk=author.pk, open_library_key__isnull=True).update(
            open_library_key=key, updated_at=timezone.now()
        )
    except IntegrityError:
        return
    author.open_library_key = key


@dataclass
class WorkItem:
    title: str
    work_key: str | None
    first_publish_year: int | None
    cover_url: str
    book_id: int | None = None
    series_name: str = ""
    series_number: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "work_key": self.work_key,
            "first_publish_year": self.first_publish_year,
            "cover_url": self.cover_url,
            "book_id": self.book_id,
            "series_name": self.series_name or None,
            # A string like "2.0", as on book detail (DRF DecimalField).
            "series_number": None if self.series_number is None else str(self.series_number),
        }


def merged_bibliography(author_key: str) -> list[AuthorWork]:
    """The best-known works plus the newest ones, one per work key, oldest first."""
    seen: dict[str, AuthorWork] = {}
    for sort in ("editions", "new"):
        for work in open_library.author_works(author_key, sort=sort):
            seen.setdefault(work.work_key, work)
    by_title: dict[str, AuthorWork] = {}
    for work in seen.values():
        name = normalize.normalize_title(work.title) or work.title.casefold()
        if name not in by_title or work.edition_count > by_title[name].edition_count:
            by_title[name] = work
    return sorted(by_title.values(), key=lambda w: (w.first_publish_year or 9999, w.title))


def author_works_for(author: Author, author_key: str | None) -> list[WorkItem]:
    """Open Library works (if author_key) matched to catalog books, plus the author's
    catalog books Open Library doesn't list. Raises BookSourceError."""
    books = _author_books(author)
    by_key = {b.open_library_key: b for b in books if b.open_library_key}
    by_title = {}
    for book in books:
        by_title.setdefault(normalize.normalize_title(book.title), book)

    items: list[WorkItem] = []
    used: set[int] = set()
    for work in merged_bibliography(author_key) if author_key else ():
        book = by_key.get(work.work_key) or by_title.get(normalize.normalize_title(work.title))
        if book is not None and book.pk in used:
            book = None  # two works can't both be one catalog book
        item = WorkItem(work.title, work.work_key, work.first_publish_year, work.cover_url)
        if book is not None:
            _use_book(item, book)
            used.add(book.pk)
        items.append(item)

    for book in books:
        if book.pk not in used:
            year = book.published_date.year if book.published_date else None
            item = WorkItem(book.title, book.open_library_key, year, book.cover_url)
            items.append(_use_book(item, book))
    return items


def _use_book(item: WorkItem, book: Book) -> WorkItem:
    item.book_id = book.pk
    item.title = book.title  # the catalog title is the one the reader knows
    item.cover_url = book.cover_url or item.cover_url
    item.series_name, item.series_number = book.series_name, book.series_number
    return item


def group_by_series(items: list[WorkItem], shelves: dict[int, dict]) -> list[dict]:
    """[{series_name, works}] : each series (earliest first, books by number), then the
    books in no known series (series_name null), oldest first."""

    def entry(item: WorkItem) -> dict:
        return {**item.as_dict(), "shelf": shelves.get(item.book_id) if item.book_id else None}

    series: dict[str, list[WorkItem]] = {}
    others: list[WorkItem] = []
    for item in items:
        if item.series_name:
            series.setdefault(item.series_name, []).append(item)
        else:
            others.append(item)

    def year(item: WorkItem) -> int:
        return item.first_publish_year or 9999

    groups = []
    for name, members in sorted(
        series.items(), key=lambda kv: (min(year(i) for i in kv[1]), kv[0].casefold())
    ):
        members.sort(key=lambda i: (i.series_number is None, i.series_number or 0, year(i)))
        groups.append({"series_name": name, "works": [entry(i) for i in members]})
    if others:
        others.sort(key=lambda i: (year(i), i.title.casefold()))
        groups.append({"series_name": None, "works": [entry(i) for i in others]})
    return groups


# --- Author IDs for links (search results, shelf entries) -----------------------------


def author_ids_for(results: list[BookResult]) -> list[list[int | None]]:
    """For each search result, the catalog Author id of each listed author, or None.

    By Open Library key first, then normalized name (the oldest such author). Two queries
    for the whole page, so search results can link authors already in the catalog.
    """
    refs: list[AuthorRef] = [ref for result in results for ref in result.authors]
    keys = {ref.open_library_key for ref in refs if ref.open_library_key}
    names = {normalize.normalize_author_name(ref.name) for ref in refs}
    by_key = dict(
        Author.objects.filter(open_library_key__in=keys).values_list("open_library_key", "id")
    )

    by_name: dict[str, int] = {}
    for normalized, author_id in (
        Author.objects.annotate(normalized=_normalized_author_name(F("name")))
        .filter(normalized__in=names)
        .order_by("-created_at", "-id")  # oldest last, so it wins in the dict
        .values_list("normalized", "id")
    ):
        by_name[normalized] = author_id
    return [
        [
            by_key.get(ref.open_library_key or "")
            or by_name.get(normalize.normalize_author_name(ref.name))
            for ref in result.authors
        ]
        for result in results
    ]

"""Nightly metadata enrichment (C-6): fill in missing descriptions and genres from Open
Library, since recommendations (R-1) are built from them.

For each catalog book missing a description or genres:

1. No Open Library key but an ISBN-13: look the ISBN up, ISBN_BATCH per request, and keep a
   work whose title is compatible (some Open Library ISBNs point at the wrong work). The
   key is saved on the book unless another catalog book already has it (a duplicate for
   merge_duplicate_books to review).
2. Fetch the work (open_library.get_work: the work JSON plus its search doc) and fill only
   fields that are still empty. Hand edits and Google data are never overwritten.
3. Authors without an Open Library key get the work's key for the same normalized name,
   unless another author row already has it. Author pages (C-5) need these keys.

Every book looked up, found or not, gets enrichment_checked_at, and isn't looked up again
for RECHECK_AFTER. A book whose lookup failed (Open Library unreachable) is left unmarked,
so the next run tries again. Requests go through open_library's 1-per-second throttle.
"""

import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from django.db import IntegrityError
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from catalog.models import Author, Book

from . import normalize, open_library
from .types import BookNotFoundError, BookResult, BookSourceError

logger = logging.getLogger(__name__)

RECHECK_AFTER = dt.timedelta(days=30)
ISBN_BATCH = open_library.ISBN_BATCH_SIZE
# Seconds to wait before the 2nd and 3rd attempt of a failed lookup (PRD: background
# jobs retry up to 3 times with backoff). The HTTP session also retries 429/5xx once.
RETRY_DELAYS = (2, 5)
# This many failed lookups in a row means Open Library is down: stop for tonight.
MAX_CONSECUTIVE_FAILURES = 5

T = TypeVar("T")


@dataclass
class EnrichmentReport:
    checked: int = 0  # looked up in Open Library (found or not)
    descriptions: int = 0
    genres: int = 0
    work_keys: int = 0  # Open Library keys found by ISBN and saved
    duplicate_works: int = 0  # ISBN matched a work another catalog book already has
    author_keys: int = 0
    duplicate_authors: int = 0  # the author's key belongs to another author row
    not_found: int = 0  # no work for the key, or no compatible work for the ISBN
    failed: int = 0  # Open Library unreachable after retries; tried again next run
    stopped: str = ""  # why the run ended early, if it did


@dataclass
class Coverage:
    books: int
    without_description: int
    without_genres: int
    unreachable: int  # missing data, but no Open Library key or ISBN to look up


class SourceDownError(Exception):
    """Too many lookups failed in a row."""


def missing_metadata() -> Q:
    return Q(description="") | Q(genres=[])


def due_books(now: dt.datetime) -> QuerySet[Book]:
    """Books missing metadata that can be looked up and weren't checked recently."""
    return (
        Book.objects.filter(missing_metadata())
        .filter(Q(open_library_key__isnull=False) | ~Q(isbn_13=""))
        .filter(
            Q(enrichment_checked_at__isnull=True) | Q(enrichment_checked_at__lt=now - RECHECK_AFTER)
        )
        .order_by(F("enrichment_checked_at").asc(nulls_first=True), "id")
    )


def coverage() -> Coverage:
    missing = Book.objects.filter(missing_metadata())
    return Coverage(
        books=Book.objects.count(),
        without_description=Book.objects.filter(description="").count(),
        without_genres=Book.objects.filter(genres=[]).count(),
        unreachable=missing.filter(open_library_key__isnull=True, isbn_13="").count(),
    )


def enrich_books(
    stop_at: float | None = None, now: dt.datetime | None = None, limit: int | None = None
) -> EnrichmentReport:
    """Enrich due books until done, out of time (time.monotonic() >= stop_at) or Open
    Library looks down. Safe to stop at any point: progress is saved per book."""
    now = now or timezone.now()
    report = EnrichmentReport()
    run = _Run(report, now)
    ids = list(due_books(now).values_list("pk", flat=True)[:limit])
    try:
        for start in range(0, len(ids), ISBN_BATCH):
            chunk_ids = ids[start : start + ISBN_BATCH]
            by_id = Book.objects.prefetch_related("authors").in_bulk(chunk_ids)
            books = [by_id[pk] for pk in chunk_ids if pk in by_id]
            work_keys = run.resolve_work_keys(books, stop_at)
            for book in books:
                if _out_of_time(stop_at):
                    report.stopped = "out of time"
                    return report
                run.enrich(book, book.open_library_key or work_keys.get(book.pk))
    except SourceDownError:
        report.stopped = f"Open Library failed {MAX_CONSECUTIVE_FAILURES} times in a row"
    return report


def _out_of_time(stop_at: float | None) -> bool:
    return stop_at is not None and time.monotonic() >= stop_at


class _Run:
    def __init__(self, report: EnrichmentReport, now: dt.datetime):
        self.report = report
        self.now = now
        self.failures_in_a_row = 0

    def call(self, fn: Callable[..., T], *args) -> T:
        """fn(*args) with retries. BookNotFoundError passes straight through."""
        for delay in (*RETRY_DELAYS, None):
            try:
                result = fn(*args)
            except BookSourceError:
                if delay is None:
                    self.failures_in_a_row += 1
                    if self.failures_in_a_row >= MAX_CONSECUTIVE_FAILURES:
                        raise SourceDownError from None
                    raise
                time.sleep(delay)
            else:
                self.failures_in_a_row = 0
                return result
        raise AssertionError("unreachable")

    def mark_checked(self, book: Book) -> None:
        # Not a content change, so updated_at is left alone.
        Book.objects.filter(pk=book.pk).update(enrichment_checked_at=self.now)
        self.report.checked += 1

    def resolve_work_keys(self, books: list[Book], stop_at: float | None) -> dict[int, str]:
        """{book id: work key} for books with an ISBN but no Open Library key."""
        lookups = [b for b in books if not b.open_library_key and b.isbn_13]
        if not lookups or _out_of_time(stop_at):
            return {}
        try:
            found = self.call(open_library.search_by_isbns, [b.isbn_13 for b in lookups])
        except BookSourceError:
            # Not marked checked: the books in this batch get another try next run.
            self.report.failed += len(lookups)
            logger.warning("ISBN lookup failed for %d books", len(lookups))
            return {}

        keys: dict[int, str] = {}
        for book in lookups:
            match = next(
                (
                    r
                    for r in found.get(book.isbn_13, ())
                    if normalize.titles_compatible(book.title, r.title)
                ),
                None,
            )
            if match is None:
                continue
            keys[book.pk] = match.source_id
            if self._save_work_key(book, match.source_id):
                self.report.work_keys += 1
            else:
                self.report.duplicate_works += 1
        return keys

    def _save_work_key(self, book: Book, key: str) -> bool:
        if Book.objects.filter(open_library_key=key).exclude(pk=book.pk).exists():
            return False
        try:
            Book.objects.filter(pk=book.pk, open_library_key__isnull=True).update(
                open_library_key=key, updated_at=self.now
            )
        except IntegrityError:  # saved by a concurrent request since the check above
            return False
        return True

    def enrich(self, book: Book, work_key: str | None) -> None:
        if not work_key:
            self.report.not_found += 1
            self.mark_checked(book)
            return
        try:
            work = self.call(open_library.get_work, work_key)
        except BookNotFoundError:
            self.report.not_found += 1
            self.mark_checked(book)
            return
        except BookSourceError:
            self.report.failed += 1
            logger.warning("Open Library lookup failed for book %s", book.pk)
            return
        self._fill(book, work)
        self._fill_author_keys(book, work)
        self.mark_checked(book)

    def _fill(self, book: Book, work: BookResult) -> None:
        # Filtered updates: a field filled since this book was read is never overwritten.
        if not book.description and work.description:
            self.report.descriptions += Book.objects.filter(pk=book.pk, description="").update(
                description=work.description, updated_at=self.now
            )
        if not book.genres and work.genres:
            self.report.genres += Book.objects.filter(pk=book.pk, genres=[]).update(
                genres=list(work.genres), updated_at=self.now
            )

    def _fill_author_keys(self, book: Book, work: BookResult) -> None:
        keyed = {
            normalize.normalize_author_name(ref.name): ref.open_library_key
            for ref in work.authors
            if ref.open_library_key
        }
        for author in book.authors.all():
            key = keyed.get(normalize.normalize_author_name(author.name))
            if author.open_library_key or not key:
                continue
            if Author.objects.filter(open_library_key=key).exists():
                self.report.duplicate_authors += 1
                continue
            try:
                updated = Author.objects.filter(pk=author.pk, open_library_key__isnull=True).update(
                    open_library_key=key, updated_at=self.now
                )
            except IntegrityError:
                self.report.duplicate_authors += 1
                continue
            self.report.author_keys += updated

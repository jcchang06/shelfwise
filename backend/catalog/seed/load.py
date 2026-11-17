"""Loading the catalog seed (C-3) built by build_catalog_seed, and removing it.

Loading plans everything in memory first (so --dry-run writes nothing), then writes in
batches of BATCH_SIZE books, one transaction per batch. Running it again is safe: a record
is skipped when the catalog already has the book, by

- the same Open Library work key,
- the same ISBN-13, or
- the same normalized title + first author (merge_duplicate_books' rule),

checked against the catalog as it is at load time (the file may have been built against
another database). Authors match like catalog saves (catalog.get_or_create_author): by
Open Library key; else an author with no key and the same normalized name, who gets the
key; else a new author.

Removal deletes only seeded books with no shelf entry and no reading log, plus the authors
left with no books, and only with the token printed by a dry run of that exact plan.
"""

import gzip
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.db import transaction
from django.db.models import Exists, F, OuterRef, QuerySet
from django.utils import timezone

from catalog.dates import parse_partial_date
from catalog.models import Author, Book, BookAuthor
from catalog.services import normalize
from catalog.services.catalog import _normalized_author_name
from tracking.models import ReadingLog, UserBook

BATCH_SIZE = 500
_WORK_KEY = re.compile(r"^OL\d+W$")
_AUTHOR_KEY = re.compile(r"^OL\d+A$")
_ISBN_13 = re.compile(r"^\d{13}$")


@dataclass
class LoadReport:
    records: int = 0
    created: int = 0
    existing_key: int = 0  # same Open Library work already in the catalog
    existing_isbn: int = 0
    existing_title_author: int = 0
    invalid: int = 0  # missing key, title or author
    authors_matched: int = 0  # distinct authors already in the catalog
    authors_keyed: int = 0  # existing keyless authors given their Open Library key
    authors_created: int = 0
    pools: dict[str, int] = field(default_factory=dict)


def read_seed(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _valid(record: dict[str, Any]) -> bool:
    authors = record.get("authors") or []
    return bool(
        _WORK_KEY.match(str(record.get("work_key", "")))
        and str(record.get("title", "")).strip()
        and authors
        and all(_AUTHOR_KEY.match(str(a.get("key", ""))) and a.get("name") for a in authors)
    )


def _name_key(title: str, author: str) -> tuple[str, str]:
    return normalize.normalize_title(title), normalize.normalize_author_name(author)


class _Catalog:
    """The parts of the catalog loading checks against, in memory."""

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.isbns: set[str] = set()
        self.names: set[tuple[str, str]] = set()
        for book in Book.objects.prefetch_related("book_authors__author"):
            links = sorted(book.book_authors.all(), key=lambda link: link.position)
            first = links[0].author.name if links else ""
            self._add(book.open_library_key, book.isbn_13, book.title, first)
        self.author_by_key: dict[str, int] = dict(
            Author.objects.exclude(open_library_key=None).values_list("open_library_key", "id")
        )
        # Keyless authors by normalized name, oldest first (it wins, as in catalog saves).
        self.keyless_by_name: dict[str, int] = {}
        for normalized, author_id in (
            Author.objects.filter(open_library_key=None)
            .annotate(normalized=_normalized_author_name(F("name")))
            .order_by("-created_at", "-id")
            .values_list("normalized", "id")
        ):
            self.keyless_by_name[normalized] = author_id

    def _add(self, key, isbn, title, first_author) -> None:
        if key:
            self.keys.add(key)
        if isbn:
            self.isbns.add(isbn)
        self.names.add(_name_key(title, first_author))

    def skip_reason(self, record: dict[str, Any]) -> str | None:
        if record["work_key"] in self.keys:
            return "existing_key"
        if record.get("isbn_13") and record["isbn_13"] in self.isbns:
            return "existing_isbn"
        if _name_key(record["title"], record["authors"][0]["name"]) in self.names:
            return "existing_title_author"
        return None

    def accept(self, record: dict[str, Any]) -> None:
        """Count the record as in the catalog, so a later copy in the file is skipped."""
        self._add(
            record["work_key"],
            record.get("isbn_13"),
            record["title"],
            record["authors"][0]["name"],
        )


def plan_load(records: list[dict[str, Any]], report: LoadReport) -> tuple[list, _Catalog]:
    """The records to create, in file order. Fills the report's skip counts."""
    catalog = _Catalog()
    to_create = []
    for record in records:
        report.records += 1
        if not _valid(record):
            report.invalid += 1
            continue
        reason = catalog.skip_reason(record)
        if reason:
            setattr(report, reason, getattr(report, reason) + 1)
            continue
        catalog.accept(record)
        to_create.append(record)
        pool = record.get("pool") or "unknown"
        report.pools[pool] = report.pools.get(pool, 0) + 1
    report.created = len(to_create)
    return to_create, catalog


def _plan_authors(to_create, catalog: _Catalog, report: LoadReport) -> None:
    """Count distinct authors for the report: already in the catalog (by key, or keyless
    with the same name, who'd get the key) or new. Same decisions as _resolve_authors."""
    decided: set[str] = set()
    keyed: set[int] = set()
    for record in to_create:
        for ref in _unique_authors(record["authors"]):
            key = ref["key"]
            if key in decided:
                continue
            decided.add(key)
            if key in catalog.author_by_key:
                report.authors_matched += 1
                continue
            keyless = catalog.keyless_by_name.get(normalize.normalize_author_name(ref["name"]))
            if keyless is not None and keyless not in keyed:
                keyed.add(keyless)
                report.authors_keyed += 1
                report.authors_matched += 1
            else:
                report.authors_created += 1


def _resolve_authors(batch, catalog: _Catalog) -> dict[str, int]:
    """{author key: author id} for one batch, creating or keying authors as needed."""
    ids: dict[str, int] = {}
    new: dict[str, Author] = {}
    for record in batch:
        for ref in record["authors"]:
            key = ref["key"]
            if key in ids or key in new:
                continue
            if key in catalog.author_by_key:
                ids[key] = catalog.author_by_key[key]
                continue
            keyless = catalog.keyless_by_name.pop(
                normalize.normalize_author_name(ref["name"]), None
            )
            if keyless is not None:
                Author.objects.filter(pk=keyless, open_library_key=None).update(
                    open_library_key=key, updated_at=timezone.now()
                )
                ids[key] = catalog.author_by_key[key] = keyless
            else:
                new[key] = Author(name=ref["name"][:255], open_library_key=key)
    for author in Author.objects.bulk_create(new.values()):
        ids[author.open_library_key] = catalog.author_by_key[author.open_library_key] = author.pk
    return ids


def _book(record: dict[str, Any], now) -> Book:
    year = record.get("first_publish_year")
    published, precision = parse_partial_date(str(year) if year else "")
    isbn = record.get("isbn_13") or ""
    return Book(
        open_library_key=record["work_key"],
        title=record["title"][:500],
        description=record.get("description") or "",
        genres=list(record.get("genres") or []),
        page_count=record.get("page_count") or None,
        published_date=published,
        published_date_precision=precision,
        isbn_13=isbn if _ISBN_13.match(isbn) else "",
        cover_url=(record.get("cover_url") or "")[:500],
        seeded_at=now,
    )


def load_seed(
    path: Path, dry_run: bool = False, progress: Callable[[str], None] = lambda m: None
) -> LoadReport:
    report = LoadReport()
    to_create, catalog = plan_load(list(read_seed(path)), report)
    _plan_authors(to_create, catalog, report)
    if dry_run:
        return report

    now = timezone.now()
    for start in range(0, len(to_create), BATCH_SIZE):
        batch = to_create[start : start + BATCH_SIZE]
        with transaction.atomic():
            author_ids = _resolve_authors(batch, catalog)
            books = Book.objects.bulk_create([_book(record, now) for record in batch])
            BookAuthor.objects.bulk_create(
                [
                    BookAuthor(book=book, author_id=author_ids[ref["key"]], position=position)
                    for book, record in zip(books, batch, strict=True)
                    for position, ref in enumerate(_unique_authors(record["authors"]))
                ]
            )
        progress(f"Loaded {min(start + BATCH_SIZE, len(to_create))} of {len(to_create)} books")
    return report


def _unique_authors(refs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    return [r for r in refs if not (r["key"] in seen or seen.add(r["key"]))]


# --- Removal -------------------------------------------------------------------------


def removable_books() -> QuerySet[Book]:
    """Seeded books that nobody has shelved or logged."""
    return (
        Book.objects.filter(seeded_at__isnull=False)
        .exclude(Exists(UserBook.objects.filter(book=OuterRef("pk"))))
        .exclude(Exists(ReadingLog.objects.filter(book=OuterRef("pk"))))
    )


def orphaned_authors(book_ids: list[int]) -> list[int]:
    """Authors whose every book is in book_ids (they'd have none left)."""
    keep = BookAuthor.objects.filter(author=OuterRef("pk")).exclude(book_id__in=book_ids)
    return list(
        Author.objects.filter(book_authors__book_id__in=book_ids)
        .exclude(Exists(keep))
        .distinct()
        .order_by("id")
        .values_list("id", flat=True)
    )


@dataclass
class RemovalPlan:
    book_ids: list[int]
    author_ids: list[int]

    @property
    def token(self) -> str:
        payload = json.dumps([self.book_ids, self.author_ids]).encode()
        return hashlib.sha256(payload).hexdigest()[:16]


def removal_plan() -> RemovalPlan:
    book_ids = list(removable_books().order_by("id").values_list("id", flat=True))
    return RemovalPlan(book_ids, orphaned_authors(book_ids))


def remove_seed(plan: RemovalPlan) -> tuple[int, int]:
    """Delete exactly the plan's books and authors. Returns (books, authors) deleted."""
    with transaction.atomic():
        _, books = Book.objects.filter(pk__in=plan.book_ids).delete()
        _, authors = Author.objects.filter(pk__in=plan.author_ids).delete()
    return books.get("catalog.Book", 0), authors.get("catalog.Author", 0)

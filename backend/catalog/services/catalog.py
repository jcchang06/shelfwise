"""Saving books into the shared catalog (C-2).

get_or_create_book() is the only way books enter the catalog from an API, so the
matching rules live in one place:

1. Same source ID (google_books_id / open_library_key) -> that book; no API call.
2. Same ISBN-13 -> the oldest such book. Its missing source ID and empty fields
   are filled in, so a book found once via each source stays one row.
3. Otherwise a new book.

Authors match by Open Library key when there is one, otherwise by normalized name
(lowercase, no periods, single spaces). Two different people with the same name
would merge; accepted for v1.
"""

import logging

from django.db import IntegrityError, transaction
from django.db.models import F, Func, QuerySet, Value
from django.db.models.functions import Lower, Replace, Trim

from catalog.dates import parse_partial_date
from catalog.models import Author, Book, BookAuthor

from . import google_books, normalize, open_library
from .types import AuthorRef, BookResult, Source

logger = logging.getLogger(__name__)

_ID_FIELD = {
    Source.GOOGLE_BOOKS: "google_books_id",
    Source.OPEN_LIBRARY: "open_library_key",
}


def fetch_book(source: Source, source_id: str) -> BookResult:
    """Full metadata from the source. Raises BookNotFoundError / BookSourceError."""
    if source == Source.GOOGLE_BOOKS:
        return google_books.get_volume(source_id)
    return open_library.get_work(source_id)


def get_or_create_book(source: Source | str, source_id: str) -> tuple[Book, bool]:
    """Return (book, created). Only calls the source API if the book isn't saved yet."""
    source = Source(source)
    id_field = _ID_FIELD[source]

    existing = Book.objects.filter(**{id_field: source_id}).first()
    if existing:
        return existing, False

    result = fetch_book(source, source_id)

    try:
        with transaction.atomic():
            return _save(result, id_field)
    except IntegrityError:
        # Another request saved the same source ID between our check and insert.
        return Book.objects.get(**{id_field: source_id}), False


def _save(result: BookResult, id_field: str) -> tuple[Book, bool]:
    published_date, precision = parse_partial_date(result.published_date)
    fields = {
        "title": result.title,
        "description": result.description,
        "genres": list(result.genres),
        "page_count": result.page_count,
        "published_date": published_date,
        "published_date_precision": precision,
        "isbn_13": result.isbn_13,
        "cover_url": result.cover_url,
    }

    match = _oldest_with_isbn(result.isbn_13)
    if match:
        _fill_gaps(match, fields, id_field, result.source_id)
        if not match.book_authors.exists():
            _link_authors(match, result.authors)
        return match, False

    book = Book.objects.create(**fields, **{id_field: result.source_id})
    _link_authors(book, result.authors)
    return book, True


def _oldest_with_isbn(isbn_13: str) -> Book | None:
    if not isbn_13:
        return None
    return (
        Book.objects.select_for_update()
        .filter(isbn_13=isbn_13)
        .order_by("created_at", "id")
        .first()
    )


def _fill_gaps(book: Book, fields: dict, id_field: str, source_id: str) -> None:
    """Fill only what the existing book lacks; never overwrite data already there."""
    changed: list[str] = []
    if not getattr(book, id_field):
        setattr(book, id_field, source_id)
        changed.append(id_field)
    for name in ("description", "genres", "page_count", "cover_url"):
        if not getattr(book, name) and fields[name]:
            setattr(book, name, fields[name])
            changed.append(name)
    if book.published_date is None and fields["published_date"]:
        book.published_date = fields["published_date"]
        book.published_date_precision = fields["published_date_precision"]
        changed += ["published_date", "published_date_precision"]
    if changed:
        book.save(update_fields=[*changed, "updated_at"])
        logger.info("Filled %s on book %s from an ISBN match", ", ".join(changed), book.pk)


# --- Authors ------------------------------------------------------------------


def _normalized_author_name(expression):
    """Database version of normalize.normalize_author_name (Postgres regexp_replace)."""
    no_periods = Lower(Replace(expression, Value("."), Value("")))
    collapsed = Func(no_periods, Value(r"\s+"), Value(" "), Value("g"), function="REGEXP_REPLACE")
    return Trim(collapsed)


def authors_matching_name(name: str) -> QuerySet[Author]:
    # Scans the authors table; fine at Phase 1 size. If the C-3 seed makes this slow,
    # add an indexed name_normalized column (a migration) instead.
    return (
        Author.objects.annotate(normalized=_normalized_author_name(F("name")))
        .filter(normalized=normalize.normalize_author_name(name))
        .order_by("created_at", "id")
    )


def get_or_create_author(ref: AuthorRef) -> Author:
    if ref.open_library_key:
        by_key = Author.objects.filter(open_library_key=ref.open_library_key).first()
        if by_key:
            return by_key
        # A keyless author with this name is the same person; give them the key.
        # An author with a *different* key is someone else, so don't match those.
        by_name = authors_matching_name(ref.name).filter(open_library_key__isnull=True).first()
        if by_name:
            by_name.open_library_key = ref.open_library_key
            by_name.save(update_fields=["open_library_key", "updated_at"])
            return by_name
        return Author.objects.create(name=ref.name, open_library_key=ref.open_library_key)

    by_name = authors_matching_name(ref.name).first()
    return by_name or Author.objects.create(name=ref.name)


def _link_authors(book: Book, refs: tuple[AuthorRef, ...]) -> None:
    linked: set[int] = set()
    for ref in refs:
        author = get_or_create_author(ref)
        if author.pk in linked:  # sources sometimes list the same author twice
            continue
        BookAuthor.objects.create(book=book, author=author, position=len(linked))
        linked.add(author.pk)


# --- Search helpers -----------------------------------------------------------


def catalog_ids_for(results: list[BookResult]) -> list[int | None]:
    """For each search result, the ID of the catalog book it would save to, or None.

    Uses the same matching as get_or_create_book (source ID, then oldest ISBN-13),
    so the UI can mark books that are already in the catalog.
    """
    google_ids = {r.source_id for r in results if r.source == Source.GOOGLE_BOOKS}
    ol_keys = {r.source_id for r in results if r.source == Source.OPEN_LIBRARY}
    isbns = {r.isbn_13 for r in results if r.isbn_13}

    by_google = dict(
        Book.objects.filter(google_books_id__in=google_ids).values_list("google_books_id", "id")
    )
    by_ol = dict(
        Book.objects.filter(open_library_key__in=ol_keys).values_list("open_library_key", "id")
    )
    by_isbn: dict[str, int] = {}
    for isbn, book_id in (
        Book.objects.filter(isbn_13__in=isbns)
        .order_by("-created_at", "-id")  # oldest last, so it wins in the dict
        .values_list("isbn_13", "id")
    ):
        by_isbn[isbn] = book_id

    ids: list[int | None] = []
    for r in results:
        by_source = by_google if r.source == Source.GOOGLE_BOOKS else by_ol
        ids.append(by_source.get(r.source_id) or by_isbn.get(r.isbn_13))
    return ids

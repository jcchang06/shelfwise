"""Find the catalog book for each Goodreads row (I-1), cheapest source first.

1. Catalog, by ISBN-13 (oldest book with it).
2. Catalog, by first author + normalized title.
3. Open Library, by ISBN, batched (prefetch_isbns): one search.json request per
   ISBN_BATCH_SIZE rows, throttled to their published rate. A hit is used only if its
   title is compatible with the row's: some Open Library ISBNs point at the wrong work.
4. Google Books, by title + author, within IMPORT_GOOGLE_DAILY_BUDGET. A result is used
   only on an exact normalized title AND first-author match; anything less is unmatched
   (a wrong match is worse than a manual one, I-4).

External hits are saved from the result already in hand (save_book_result), never with a
follow-up single-book request. Matching never touches shelves; applying a match is the
processing step's job.
"""

import logging
from dataclasses import dataclass

from catalog.models import Book
from catalog.services import google_books, open_library
from catalog.services.catalog import authors_matching_name, save_book_result
from catalog.services.normalize import normalize_author_name, normalize_title, titles_compatible
from catalog.services.types import BookResult, BookSourceError

from .budget import BudgetExhaustedError, spend_google_call
from .models import ImportRow

logger = logging.getLogger(__name__)
Method = ImportRow.MatchMethod


@dataclass
class Match:
    book: Book | None
    method: str = ""  # ImportRow.MatchMethod value when book is set
    note: str = ""  # why it didn't match (or anything worth telling the reader)


class MatchPausedError(Exception):
    """Matching can't continue today (the Google budget or quota is used up). The row is
    left pending and the import pauses; nothing about the row is wrong."""


def first_author(row: ImportRow) -> str:
    return row.author.split(",")[0].strip()


def prefetch_isbns(rows: list[ImportRow]) -> dict[str, list[BookResult]]:
    """Open Library results for every row ISBN not already in the catalog, batched."""
    isbns = {r.isbn_13 for r in rows if r.isbn_13}
    in_catalog = set(Book.objects.filter(isbn_13__in=isbns).values_list("isbn_13", flat=True))
    missing = sorted(isbns - in_catalog)
    if not missing:
        return {}
    try:
        return open_library.search_by_isbns(missing)
    except BookSourceError as exc:
        # Not fatal: those rows fall through to title + author matching.
        logger.warning("Open Library ISBN batch failed: %s", exc)
        return {}


def _catalog_by_isbn(row: ImportRow) -> Book | None:
    if not row.isbn_13:
        return None
    return Book.objects.filter(isbn_13=row.isbn_13).order_by("created_at", "id").first()


def _catalog_by_title(row: ImportRow) -> Book | None:
    author = first_author(row)
    if not author:
        return None
    wanted = normalize_title(row.title)
    candidates = (
        Book.objects.filter(book_authors__author__in=authors_matching_name(author))
        .distinct()
        .order_by("created_at", "id")
    )
    return next((b for b in candidates if normalize_title(b.title) == wanted), None)


def _same_book(result: BookResult, row: ImportRow) -> bool:
    """Exact normalized title, and the row's first author among the result's authors."""
    if normalize_title(result.title) != normalize_title(row.title):
        return False
    wanted = normalize_author_name(first_author(row))
    return any(normalize_author_name(a.name) == wanted for a in result.authors)


def _google_by_title(row: ImportRow) -> tuple[BookResult | None, str]:
    author = first_author(row)
    if not author:
        return None, "No author to search by."
    try:
        spend_google_call()
    except BudgetExhaustedError as exc:
        raise MatchPausedError(str(exc)) from exc
    query = f'intitle:"{row.title}" inauthor:"{author}"'
    try:
        results = google_books.search(query)
    except google_books.QuotaExceededError as exc:
        raise MatchPausedError(
            "Google Books' daily quota is used up until midnight Pacific."
        ) from exc
    except BookSourceError:
        return None, "Google Books couldn't be reached."
    hit = next((r for r in results if _same_book(r, row)), None)
    if hit:
        return hit, ""
    if results:
        return None, "Google Books found similar books but none with this exact title and author."
    return None, "No book with this title and author found."


def match_row(row: ImportRow, ol_by_isbn: dict[str, list[BookResult]]) -> Match:
    """The catalog book for one row (saving an external hit), or Match(None, note=why)."""
    if book := _catalog_by_isbn(row):
        return Match(book, Method.CATALOG_ISBN)
    if book := _catalog_by_title(row):
        return Match(book, Method.CATALOG_TITLE)

    notes: list[str] = []
    if row.isbn_13:
        candidates = ol_by_isbn.get(row.isbn_13, [])
        hit = next((r for r in candidates if titles_compatible(r.title, row.title)), None)
        if hit:
            book, _ = save_book_result(hit)
            return Match(book, Method.ISBN)
        if candidates:
            notes.append(
                f"ISBN {row.isbn_13} belongs to “{candidates[0].title}” in Open Library, "
                "not this book."
            )
        else:
            notes.append(f"ISBN {row.isbn_13} wasn't found.")

    hit, note = _google_by_title(row)
    if hit:
        book, _ = save_book_result(hit)
        return Match(book, Method.TITLE_AUTHOR)
    notes.append(note)
    return Match(None, note=" ".join(n for n in notes if n))

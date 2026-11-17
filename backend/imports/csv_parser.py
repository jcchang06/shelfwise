"""Parse a Goodreads library export into ImportRow-ready values (I-1). No I/O, no DB.

Goodreads exports: UTF-8 (sometimes with a BOM), one header row, ISBNs wrapped as
="9780593135204" so spreadsheets keep leading zeros, dates as 2023/05/14, ratings 0-5
(0 = unrated), the series inside the title: "Leviathan Wakes (The Expanse, #1)".
"""

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from catalog.services.normalize import clean_description, clean_text, isbn10_to_13
from tracking.models import UserBook

Status = UserBook.Status

# Columns we rely on. Others (Average Rating, Private Notes, Owned Copies, ...) are ignored.
REQUIRED_COLUMNS = (
    "Book Id",
    "Title",
    "Author",
    "ISBN",
    "ISBN13",
    "My Rating",
    "Exclusive Shelf",
    "Bookshelves",
    "Date Read",
    "Date Added",
)

EXCLUSIVE_SHELVES = {
    "read": Status.FINISHED,
    "currently-reading": Status.READING,
    "to-read": Status.WANT_TO_READ,
}
# A custom shelf with one of these names marks a DNF (PRD I-1), whatever the exclusive shelf.
DNF_SHELVES = {"dnf", "did-not-finish"}

_SERIES = re.compile(
    r"^(?P<title>.+?)\s*\((?P<series>[^()]+?),?\s*#(?P<number>\d+(?:\.\d+)?)\)\s*$"
)
_ISBN_JUNK = re.compile(r"[=\"\s-]")


class ImportFileError(Exception):
    """The upload isn't a usable Goodreads export. The message is shown to the user."""


@dataclass
class ParsedRow:
    row_number: int
    goodreads_book_id: str
    title: str
    author: str = ""
    additional_authors: str = ""
    isbn_13: str = ""
    page_count: int | None = None
    year_published: int | None = None
    series_name: str = ""
    series_number: Decimal | None = None
    status: str = Status.WANT_TO_READ
    rating: int | None = None
    date_read: dt.date | None = None
    date_added: dt.date | None = None
    review: str = ""
    notes: list[str] = field(default_factory=list)
    error: str = ""  # non-empty: the row can't be imported (becomes a FAILED row)


# --- Field parsers ---------------------------------------------------------------------


def parse_isbn(isbn13: str, isbn10: str) -> str:
    """The row's ISBN-13: the ISBN13 column, or the ISBN column converted. "" if neither."""
    thirteen = _ISBN_JUNK.sub("", isbn13 or "")
    if re.fullmatch(r"97[89]\d{10}", thirteen):
        return thirteen
    ten = _ISBN_JUNK.sub("", isbn10 or "").upper()
    if re.fullmatch(r"\d{9}[\dX]", ten):
        return isbn10_to_13(ten)
    return ""


def split_series(raw_title: str) -> tuple[str, str, Decimal | None]:
    """ "Leviathan Wakes (The Expanse, #1)" -> ("Leviathan Wakes", "The Expanse", 1)."""
    title = clean_text(raw_title)
    match = _SERIES.match(title)
    if not match:
        return title, "", None
    return match["title"].strip(), match["series"].strip(), Decimal(match["number"])


def parse_date(value: str) -> dt.date | None:
    value = (value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_int(value: str) -> int | None:
    """A whole, non-negative number. Goodreads exports some as "5.0" or "320.0", so a
    trailing ".0" is fine; "4.5", "-1" and text are not."""
    value = (value or "").strip()
    try:
        number = float(value)
    except ValueError:
        return None
    return int(number) if number.is_integer() and number >= 0 else None


def map_status(exclusive_shelf: str, bookshelves: str) -> tuple[str, str | None]:
    """(status, note). DNF shelves win over the exclusive shelf."""
    shelves = {s.strip().lower() for s in (bookshelves or "").split(",") if s.strip()}
    if shelves & DNF_SHELVES:
        return Status.DNF, None
    exclusive = (exclusive_shelf or "").strip().lower()
    if exclusive in EXCLUSIVE_SHELVES:
        return EXCLUSIVE_SHELVES[exclusive], None
    return Status.WANT_TO_READ, f"Unknown shelf “{exclusive_shelf}” imported as Want to read."


# --- Rows and files ------------------------------------------------------------------


def map_row(row_number: int, raw: dict[str, str]) -> ParsedRow:
    """One CSV row -> ParsedRow, applying Shelfwise's rules (ratings only on finished books)."""
    goodreads_id = (raw.get("Book Id") or "").strip()
    title, series_name, series_number = split_series(raw.get("Title") or "")
    parsed = ParsedRow(row_number=row_number, goodreads_book_id=goodreads_id, title=title)
    if not goodreads_id or not title:
        parsed.error = "This row has no Goodreads Book Id or title."
        return parsed

    parsed.author = clean_text(raw.get("Author"))
    parsed.additional_authors = clean_text(raw.get("Additional Authors"))
    parsed.isbn_13 = parse_isbn(raw.get("ISBN13", ""), raw.get("ISBN", ""))
    parsed.page_count = parse_int(raw.get("Number of Pages", ""))
    parsed.year_published = parse_int(
        raw.get("Original Publication Year", "") or raw.get("Year Published", "")
    )
    parsed.series_name, parsed.series_number = series_name, series_number
    parsed.review = clean_description(raw.get("My Review"))

    parsed.status, note = map_status(raw.get("Exclusive Shelf", ""), raw.get("Bookshelves", ""))
    if note:
        parsed.notes.append(note)

    rating = parse_int(raw.get("My Rating", ""))
    if rating and 1 <= rating <= 5:
        if parsed.status == Status.FINISHED:
            parsed.rating = rating
        else:
            label = Status(parsed.status).label
            parsed.notes.append(
                f"Your {rating}★ rating wasn't imported: ratings need Finished, not {label}."
            )

    parsed.date_read = parse_date(raw.get("Date Read", ""))
    parsed.date_added = parse_date(raw.get("Date Added", ""))
    if (raw.get("Date Read") or "").strip() and parsed.date_read is None:
        parsed.notes.append(f"Couldn't read the date “{raw['Date Read']}”.")
    return parsed


def decode(data: bytes) -> str:
    if len(data) > settings.IMPORT_MAX_FILE_BYTES:
        limit_mb = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
        raise ImportFileError(f"That file is too large. The limit is {limit_mb:g} MB.")
    if not data.strip():
        raise ImportFileError("That file is empty.")
    try:
        return data.decode("utf-8-sig")  # strips a BOM if present
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            "That file isn't UTF-8 text. Upload the CSV exactly as Goodreads exported it."
        ) from exc


def parse_goodreads_csv(data: bytes) -> list[ParsedRow]:
    """Validate and parse a whole export. Raises ImportFileError for an unusable file."""
    reader = csv.DictReader(io.StringIO(decode(data), newline=""))
    headers = [h.strip() for h in reader.fieldnames or []]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise ImportFileError(
            "This doesn't look like a Goodreads export (missing columns: "
            f"{', '.join(missing)}). In Goodreads, go to My Books → Import and export → "
            "Export Library."
        )
    reader.fieldnames = headers

    rows: list[ParsedRow] = []
    seen: dict[str, int] = {}
    try:
        for number, raw in enumerate(reader, start=1):
            if number > settings.IMPORT_MAX_ROWS:
                raise ImportFileError(
                    f"That export has more than {settings.IMPORT_MAX_ROWS:,} books, the limit."
                )
            parsed = map_row(number, raw)
            first = seen.get(parsed.goodreads_book_id) if parsed.goodreads_book_id else None
            if first is not None:
                parsed.error = f"Same Goodreads book as row {first}; only the first is imported."
            elif parsed.goodreads_book_id:
                seen[parsed.goodreads_book_id] = number
            rows.append(parsed)
    except csv.Error as exc:
        raise ImportFileError(f"That CSV is malformed near row {reader.line_num}: {exc}") from exc

    if not rows:
        raise ImportFileError("That export has no books in it.")
    return rows

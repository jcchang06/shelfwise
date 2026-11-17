"""Apply a matched Goodreads row to the reader's shelf (I-1, I-3).

Three cases, decided by GoodreadsLink (user + Goodreads Book Id):

- Linked before: update the entry from Goodreads, but only if it hasn't changed in
  Shelfwise since that sync (updated_at <= link.synced_at). Otherwise skip it.
- Not linked, but the book is already on the shelf (added by hand, or another Goodreads
  edition of the same book): link it and fill only its empty fields.
- Neither: create the entry.

Shelf rules still apply (tracking.services.apply_shelf_changes): Goodreads values are
passed explicitly, so no "today" defaults sneak in. An unknown Goodreads date stays
unknown (the stats' "Date unknown" row). Imported DNFs get the reason "other" and the note
"Imported from Goodreads", since the database requires a reason; the import summary
counts how many still have it.
"""

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from catalog.models import Book
from tracking.models import UserBook
from tracking.services import ShelfRuleError, apply_shelf_changes

from .models import GoodreadsLink, ImportRow

Status = UserBook.Status
State = ImportRow.State
DNF_PLACEHOLDER_NOTE = "Imported from Goodreads"


def placeholder_dnf_count(user) -> int:
    """Imported DNFs whose reason is still the placeholder (shown on the import summary)."""
    return UserBook.objects.filter(
        user=user,
        status=Status.DNF,
        dnf_reason=UserBook.DnfReason.OTHER,
        dnf_note=DNF_PLACEHOLDER_NOTE,
    ).count()


def goodreads_changes(row: ImportRow) -> dict[str, Any]:
    """The shelf fields a row sets, with every date explicit (None = unknown)."""
    changes: dict[str, Any] = {"status": row.status, "started_at": None, "review": row.review}
    if row.status == Status.FINISHED:
        changes.update(finished_at=row.date_read, rating=row.rating)
    elif row.status == Status.DNF:
        changes.update(
            dnf_reason=UserBook.DnfReason.OTHER,
            dnf_note=DNF_PLACEHOLDER_NOTE,
            dnf_at=row.date_read,
            dnf_page=None,
        )
    return changes


def _fill_book(book: Book, row: ImportRow) -> None:
    """Goodreads knows the series; keep it if the catalog book has none."""
    if row.series_name and not book.series_name:
        book.series_name, book.series_number = row.series_name, row.series_number
        book.save(update_fields=["series_name", "series_number", "updated_at"])


def _empty_fields(entry: UserBook, row: ImportRow) -> dict[str, Any]:
    fill: dict[str, Any] = {}
    if not entry.review and row.review:
        fill["review"] = row.review
    if entry.status == Status.FINISHED:
        if entry.rating is None and row.rating is not None and row.status == Status.FINISHED:
            fill["rating"] = row.rating
        if entry.finished_at is None and row.date_read and row.status == Status.FINISHED:
            fill["finished_at"] = row.date_read
    return fill


def _save(entry: UserBook, changes: dict[str, Any], today: dt.date) -> None:
    apply_shelf_changes(entry, changes, today=today)
    entry.save()


def _sync_link(user, row: ImportRow, entry: UserBook) -> None:
    entry.refresh_from_db(fields=["updated_at"])
    GoodreadsLink.objects.update_or_create(
        user=user,
        goodreads_book_id=row.goodreads_book_id,
        defaults={"user_book": entry, "synced_at": entry.updated_at},
    )


@transaction.atomic
def apply_match(row: ImportRow, book: Book, today: dt.date | None = None) -> None:
    """Write the row to the shelf and set row.state/note/user_book (the caller saves row)."""
    user = row.goodreads_import.user
    today = today or timezone.localdate()
    row.book = book
    _fill_book(book, row)

    try:
        link = (
            GoodreadsLink.objects.select_related("user_book")
            .filter(user=user, goodreads_book_id=row.goodreads_book_id)
            .first()
        )
        existing = UserBook.objects.filter(user=user, book=book).first()

        if link and link.user_book.book_id == book.id:
            entry = link.user_book
            if entry.updated_at > link.synced_at:
                row.state, row.user_book = State.SKIPPED, entry
                row.note = _join(
                    row.note, "Changed in Shelfwise since the last import; left as is."
                )
                return
            _save(entry, goodreads_changes(row), today)
            row.state = State.UPDATED
        elif existing:
            entry = existing
            fill = _empty_fields(entry, row)
            if fill:
                _save(entry, fill, today)
                row.state = State.UPDATED
                row.note = _join(row.note, f"Already on your shelf; filled in {', '.join(fill)}.")
            else:
                row.state = State.SKIPPED
                row.note = _join(row.note, "Already on your shelf; nothing to fill in.")
        else:
            entry = UserBook(user=user, book=book)
            _save(entry, goodreads_changes(row), today)
            if row.date_added:
                # "Added" on the shelf should mean when it was added on Goodreads.
                added = dt.datetime.combine(row.date_added, dt.time(12), tzinfo=dt.UTC)
                UserBook.objects.filter(pk=entry.pk).update(created_at=added)
            row.state = State.CREATED
    except ShelfRuleError as exc:
        row.state = State.FAILED
        row.note = _join(row.note, " ".join(exc.errors.values()))
        return

    row.user_book = entry
    _sync_link(user, row, entry)


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)

"""Shelf rules (T-2, T-4, T-6): status changes, their side effects and business validation.

apply_shelf_changes() is the one place these rules live; the API serializers check types
and shape, then call it. It mutates the UserBook in memory and leaves saving to the caller.

Status change side effects (old -> new, only when the status actually changes):

    finished -> reading  started_at = today (a re-read is a new read)
    other -> reading     started_at = today only if empty (dnf -> reading resumes the
                         same read, so its original start is kept)
    any -> finished      finished_at = today (overwrites, so a re-read gets the new date)
    any -> dnf           rating cleared; dnf_at = today; dnf_page = pages logged in the
                         current read (capped at page_count, null if none); a blank
                         dnf_reason is saved as not_specified
    dnf -> any           all DNF fields cleared (logs are kept)
    finished -> reading / want_to_read
                         rating and finished_at kept (a re-read keeps its stars)

Values sent in the request always win over these defaults.
"""

import datetime as dt
from typing import Any

from django.db.models import QuerySet, Sum
from django.utils import timezone

from .models import ReadingLog, UserBook

Status = UserBook.Status

DNF_FIELDS = ("dnf_page", "dnf_at", "dnf_reason", "dnf_note")
DATE_FIELDS = ("started_at", "finished_at", "dnf_at")
EDITABLE_FIELDS = ("status", "rating", "review", "started_at", "finished_at", *DNF_FIELDS)


class ShelfRuleError(Exception):
    """One or more shelf rules were broken. `errors` maps field name -> message."""

    def __init__(self, errors: dict[str, str]):
        super().__init__(errors)
        self.errors = errors


def _empty(field: str) -> Any:
    return "" if field in ("dnf_reason", "dnf_note", "review") else None


def current_read_logs(user_book: UserBook) -> QuerySet[ReadingLog]:
    """This user's logs for this book in the current read: on or after started_at.

    With no started_at, every log counts. Earlier logs belong to a previous read, so a
    re-read's progress and DNF page start from zero. The SQL version for list queries
    is in views.shelf_for(); keep the two in step.
    """
    logs = ReadingLog.objects.filter(user=user_book.user_id, book=user_book.book_id)
    if user_book.started_at:
        logs = logs.filter(log_date__gte=user_book.started_at)
    return logs


def default_dnf_page(user_book: UserBook) -> int | None:
    """Pages logged in the current read, capped at the book's page count."""
    total = current_read_logs(user_book).aggregate(total=Sum("pages_read"))["total"]
    if not total:
        return None
    page_count = user_book.book.page_count
    return min(total, page_count) if page_count else total


def apply_shelf_changes(
    user_book: UserBook, changes: dict[str, Any], today: dt.date | None = None
) -> None:
    """Validate `changes` against the shelf rules and apply them to `user_book`.

    `changes` holds only the fields the client sent (already type-checked). Raises
    ShelfRuleError with every broken rule at once; on error `user_book` is unchanged.
    """
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"Not editable: {sorted(unknown)}")

    today = today or timezone.localdate()
    old = user_book.status
    new = changes.get("status", old)
    entering, leaving = new != old and new, new != old and old
    errors: dict[str, str] = {}

    # --- Rules on what the client sent -----------------------------------------
    # Rating (T-4): can only be set or changed when the book ends up finished. Resending
    # the current value is fine, so clients may PATCH a whole object back.
    if "rating" in changes and new != Status.FINISHED:
        unchanged = changes["rating"] == user_book.rating
        cleared_by_dnf = new == Status.DNF and changes["rating"] is None
        if not (unchanged or cleared_by_dnf):
            errors["rating"] = "You can rate a book only when it's finished."

    # DNF fields (T-6): only for books that end up DNF. Empty values are fine (no-ops).
    if new != Status.DNF:
        for field in DNF_FIELDS:
            if changes.get(field) not in (None, ""):
                errors[field] = "Only books marked DNF have this field."

    for field in DATE_FIELDS:
        value = changes.get(field)
        if value is not None and value > today:
            errors[field] = "This date can't be in the future."

    # --- Work out the resulting values -----------------------------------------
    result: dict[str, Any] = {}

    if leaving == Status.DNF:
        result.update({field: _empty(field) for field in DNF_FIELDS})

    if entering == Status.READING and (leaving == Status.FINISHED or not user_book.started_at):
        result["started_at"] = today
    elif entering == Status.FINISHED:
        result["finished_at"] = today
    elif entering == Status.DNF:
        result.update(rating=None, dnf_at=today, dnf_page=default_dnf_page(user_book))

    result.update(changes)  # what the client sent beats every default above
    if new == Status.DNF:
        result["rating"] = None  # stars and a DNF don't mix, even if the old rating was resent

    final = {field: result.get(field, getattr(user_book, field)) for field in EDITABLE_FIELDS}

    if new == Status.DNF and not final["dnf_reason"]:
        final["dnf_reason"] = UserBook.DnfReason.NOT_SPECIFIED  # the reason is optional (T-6)

    page_count = user_book.book.page_count
    if "dnf_page" in changes and changes["dnf_page"] is not None and page_count:
        if changes["dnf_page"] > page_count:
            errors["dnf_page"] = f"This book has only {page_count} pages."

    # Order only matters for a finished book: during a re-read, finished_at is the
    # previous read's date and started_at is the new one.
    if (
        new == Status.FINISHED
        and final["started_at"]
        and final["finished_at"]
        and final["started_at"] > final["finished_at"]
    ):
        errors["started_at"] = "The start date must be on or before the finish date."

    if errors:
        raise ShelfRuleError(errors)

    for field, value in final.items():
        setattr(user_book, field, value)


def shelf_entries_for(user, book_ids) -> dict[int, dict[str, Any]]:
    """{book_id: {"id": user_book_id, "status": status}} for the books on `user`'s shelf.

    One query. Used by book search to mark results already shelved; always computed per
    request (never cached), since it depends on the user and changes as they add books.
    """
    ids = [book_id for book_id in book_ids if book_id is not None]
    if not ids:
        return {}
    rows = UserBook.objects.filter(user=user, book_id__in=ids).values("id", "book_id", "status")
    return {row["book_id"]: {"id": row["id"], "status": row["status"]} for row in rows}

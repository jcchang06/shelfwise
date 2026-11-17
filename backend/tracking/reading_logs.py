"""Page log rules (T-3): adding and editing daily logs and their effect on the shelf entry.

log_pages() and update_log() are the only writers of ReadingLog besides shelf removal.
Both lock the user's shelf entry row first (SELECT ... FOR UPDATE), which serializes
concurrent writes for the same user and book. That's what makes same-day accumulation
safe: two quick POSTs can't both read the old total.

Effects on the shelf entry:
- POST on a want_to_read book moves it to reading (started_at = the log's date if empty).
- Backfill: a log dated before started_at moves started_at back to that date, unless the
  date is on or before the previous read's finished_at (it belongs to an earlier read).
- started_at never moves forward on its own.
"""

import datetime as dt
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from catalog.models import Book

from .models import ReadingLog, UserBook
from .services import apply_shelf_changes, current_read_logs

Status = UserBook.Status


class LogRuleError(Exception):
    """A page-log rule was broken. `errors` maps field -> message; `conflict_id` is set when
    the problem is another log already occupying the requested day."""

    def __init__(self, errors: dict[str, str], conflict_id: int | None = None):
        super().__init__(errors)
        self.errors = errors
        self.conflict_id = conflict_id


def pages_logged(user_book: UserBook) -> int:
    return current_read_logs(user_book).aggregate(total=Sum("pages_read"))["total"] or 0


def _check_date_and_pages(log_date: dt.date, day_total: int, today: dt.date) -> dict[str, str]:
    errors: dict[str, str] = {}
    if log_date > today:
        errors["log_date"] = "You can't log pages for a future day."
    if day_total > settings.MAX_PAGES_PER_DAY:
        errors["pages_read"] = (
            f"That would make {day_total} pages in one day; the limit is "
            f"{settings.MAX_PAGES_PER_DAY}. Check for a typo."
        )
    return errors


def _previous_read_finish(user_book: UserBook) -> dt.date | None:
    """finished_at only marks a *previous* read when it's before started_at (a re-read)."""
    started, finished = user_book.started_at, user_book.finished_at
    if started and finished and finished < started:
        return finished
    return None


def _backfill_start(user_book: UserBook, log_date: dt.date) -> bool:
    """Move started_at back to log_date when the log is earlier and belongs to this read."""
    if not user_book.started_at or log_date >= user_book.started_at:
        return False
    previous_finish = _previous_read_finish(user_book)
    if previous_finish and log_date <= previous_finish:
        return False  # an earlier read's log; this read's start stays
    user_book.started_at = log_date
    return True


def _locked_shelf_entry(user_id: int, book_id: int) -> UserBook | None:
    return (
        UserBook.objects.select_for_update()
        .select_related("book")
        .filter(user_id=user_id, book_id=book_id)
        .first()
    )


def log_pages(
    user, book: Book, pages_read: int, log_date: dt.date | None = None, today: dt.date | None = None
) -> tuple[ReadingLog, bool, UserBook]:
    """Add pages for one book on one day. Returns (log, created, shelf entry).

    A second log for the same day adds to the first. Raises LogRuleError.
    """
    today = today or timezone.localdate()
    log_date = log_date or today

    with transaction.atomic():
        user_book = _locked_shelf_entry(user.pk, book.pk)
        if user_book is None:
            raise LogRuleError({"book_id": "Add this book to your shelf first."})

        existing = ReadingLog.objects.filter(user=user, book=book, log_date=log_date).first()
        day_total = (existing.pages_read if existing else 0) + pages_read
        errors = _check_date_and_pages(log_date, day_total, today)
        if errors:
            raise LogRuleError(errors)

        if existing:
            existing.pages_read = day_total  # safe: the shelf entry lock serializes writers
            existing.save(update_fields=["pages_read", "updated_at"])
            log, created = existing, False
        else:
            log = ReadingLog.objects.create(
                user=user, book=book, log_date=log_date, pages_read=pages_read
            )
            created = True

        if user_book.status == Status.WANT_TO_READ:
            changes: dict[str, Any] = {"status": Status.READING}
            if not user_book.started_at:
                changes["started_at"] = log_date
            apply_shelf_changes(user_book, changes, today=today)
            _backfill_start(user_book, log_date)
            user_book.save()
        elif _backfill_start(user_book, log_date):
            user_book.save(update_fields=["started_at", "updated_at"])

    return log, created, user_book


def update_log(
    log: ReadingLog, changes: dict[str, Any], today: dt.date | None = None
) -> tuple[ReadingLog, UserBook | None]:
    """Set a log's pages and/or move it to another day. Never changes the shelf status."""
    unknown = set(changes) - {"pages_read", "log_date"}
    if unknown:
        raise ValueError(f"Not editable: {sorted(unknown)}")
    today = today or timezone.localdate()

    with transaction.atomic():
        user_book = _locked_shelf_entry(log.user_id, log.book_id)
        new_date = changes.get("log_date", log.log_date)
        new_pages = changes.get("pages_read", log.pages_read)

        errors = _check_date_and_pages(new_date, new_pages, today)
        if new_date != log.log_date:
            clash = (
                ReadingLog.objects.filter(user=log.user_id, book=log.book_id, log_date=new_date)
                .exclude(pk=log.pk)
                .first()
            )
            if clash:
                day = new_date.isoformat()
                errors["log_date"] = (
                    f"You already logged this book on {day}. Edit that day instead."
                )
                raise LogRuleError(errors, conflict_id=clash.pk)
        if errors:
            raise LogRuleError(errors)

        date_changed = new_date != log.log_date
        log.log_date, log.pages_read = new_date, new_pages
        log.save(update_fields=["log_date", "pages_read", "updated_at"])

        if user_book and date_changed and _backfill_start(user_book, new_date):
            user_book.save(update_fields=["started_at", "updated_at"])

    return log, user_book

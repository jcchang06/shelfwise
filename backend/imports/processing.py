"""Process an import in resumable, time-bounded batches (I-2).

process_import_batch() is the one entry point, used by:
- POST /api/imports/{id}/process/, called repeatedly while the import page is open;
- manage.py run_import <id> and manage.py run_pending_imports (the nightly job);
- the local-only Celery task.

Each batch stops after IMPORT_BATCH_SECONDS (default 20), well inside gunicorn's 60s
timeout, and saves after every row, so any interruption just means the next batch picks
up where this one stopped. A lock in the shared cache keeps two callers (the open page and
the nightly job) from processing the same import at once.
"""

import logging
import time
import uuid
from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

from .apply import apply_match
from .matching import MatchPausedError, MatchRetryLaterError, match_row, prefetch_isbns
from .models import GoodreadsImport, ImportRow

logger = logging.getLogger(__name__)
Status = GoodreadsImport.Status
State = ImportRow.State

# Rows fetched (and ISBN-prefetched) per batch; the time limit usually stops it sooner.
BATCH_ROWS = 200
LOCK_SECONDS = 120  # longer than any batch; expires on its own if a worker dies

# Rows deleted when an import finishes, or when a finished import's row is resolved or
# dismissed (PRD privacy). Unmatched rows stay for I-4; failed rows stay so the summary can
# say why.
DONE_STATES = (State.CREATED, State.UPDATED, State.SKIPPED, State.DISMISSED)


class ImportBusyError(Exception):
    """Another batch is already processing this import."""


def _lock_key(import_id: int) -> str:
    return f"imports:lock:{import_id}"


def refresh_counts(goodreads_import: GoodreadsImport) -> None:
    """Recompute the progress counters from the rows (one query).

    Only valid while every row still exists: _finish() calls it right before deleting the
    matched rows, after which the stored counters are the record and are never recomputed.
    """
    counts = dict(
        goodreads_import.rows.values_list("state").annotate(n=Count("id")).values_list("state", "n")
    )
    goodreads_import.created_count = counts.get(State.CREATED, 0)
    goodreads_import.updated_count = counts.get(State.UPDATED, 0)
    goodreads_import.skipped_count = counts.get(State.SKIPPED, 0) + counts.get(State.DISMISSED, 0)
    goodreads_import.unmatched_count = counts.get(State.UNMATCHED, 0)
    goodreads_import.failed_count = counts.get(State.FAILED, 0)
    goodreads_import.processed_rows = goodreads_import.total_rows - counts.get(State.PENDING, 0)


def _finish(goodreads_import: GoodreadsImport) -> None:
    refresh_counts(goodreads_import)
    goodreads_import.status = Status.DONE
    goodreads_import.finished_at = timezone.now()
    goodreads_import.error = ""
    goodreads_import.save()
    goodreads_import.rows.filter(state__in=DONE_STATES).delete()


def process_import_batch(
    import_id: int,
    max_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> GoodreadsImport:
    """Process pending rows until the time limit, a pause, or the end of the import.

    Returns the import with fresh counters. Raises ImportBusyError if another batch holds
    the lock. A finished import is returned unchanged.
    """
    max_seconds = settings.IMPORT_BATCH_SECONDS if max_seconds is None else max_seconds
    token = uuid.uuid4().hex
    if not cache.add(_lock_key(import_id), token, timeout=LOCK_SECONDS):
        raise ImportBusyError("This import is already being processed.")
    try:
        return _process(import_id, max_seconds, clock)
    finally:
        if cache.get(_lock_key(import_id)) == token:
            cache.delete(_lock_key(import_id))


def _process(import_id: int, max_seconds: float, clock: Callable[[], float]) -> GoodreadsImport:
    goodreads_import = GoodreadsImport.objects.select_related("user").get(pk=import_id)
    if goodreads_import.status in (Status.DONE, Status.FAILED):
        return goodreads_import

    deadline = clock() + max_seconds
    goodreads_import.status = Status.RUNNING
    goodreads_import.error = ""
    goodreads_import.save(update_fields=["status", "error", "updated_at"])

    rows = list(
        goodreads_import.rows.filter(state=State.PENDING)
        .select_related("goodreads_import__user")
        .order_by("row_number")[:BATCH_ROWS]
    )
    if not rows:
        _finish(goodreads_import)
        return goodreads_import

    ol_by_isbn = prefetch_isbns(rows)
    for row in rows:
        if clock() >= deadline:
            break
        try:
            match = match_row(row, ol_by_isbn)
        except MatchPausedError as exc:
            goodreads_import.status = Status.PAUSED
            goodreads_import.error = str(exc)
            break
        except MatchRetryLaterError:
            # Short-term rate limit: stop this batch; the row stays pending and the import
            # stays running, so the next batch (seconds later) carries on.
            logger.info("Import %s: Google rate limit, ending batch early", import_id)
            break
        except Exception:  # one bad row must never stop an import
            logger.exception("Import %s row %s failed", import_id, row.row_number)
            row.state, row.note = State.FAILED, "Something went wrong matching this row."
            row.save(update_fields=["state", "note"])
            continue

        if match.book is None:
            row.state, row.note = State.UNMATCHED, match.note
        else:
            row.match_method = match.method
            try:
                apply_match(row, match.book)
            except Exception:
                logger.exception("Import %s row %s could not be applied", import_id, row.row_number)
                row.state, row.note = State.FAILED, "Something went wrong adding this book."
        row.save()

    if (
        goodreads_import.status != Status.PAUSED
        and not goodreads_import.rows.filter(state=State.PENDING).exists()
    ):
        _finish(goodreads_import)
        return goodreads_import

    refresh_counts(goodreads_import)
    goodreads_import.save()
    return goodreads_import

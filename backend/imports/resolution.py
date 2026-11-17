"""Resolve or dismiss unmatched rows by hand (I-4).

Counters stay right in both phases of an import:
- Finished import: its matched rows are already deleted and the stored counters are the
  record, so counters are adjusted in place (with F() expressions) and a resolved or
  dismissed row is deleted too (PRD privacy). Failed rows are kept, with their reason.
- Import still running or paused: the row keeps its new state and the counters are
  recomputed from the rows, exactly as processing does; finishing deletes it later.
"""

from django.db import transaction
from django.db.models import F

from catalog.models import Book

from .apply import apply_match
from .models import GoodreadsImport, ImportRow
from .processing import DONE_STATES, refresh_counts

State = ImportRow.State

# Which counter each final row state belongs to (dismissed counts as skipped).
COUNTER = {
    State.CREATED: "created_count",
    State.UPDATED: "updated_count",
    State.SKIPPED: "skipped_count",
    State.DISMISSED: "skipped_count",
    State.FAILED: "failed_count",
}


class RowNotResolvableError(Exception):
    """The row isn't unmatched (already handled, or it failed for another reason)."""


def _locked_unmatched(row_id: int, goodreads_import: GoodreadsImport) -> ImportRow:
    row = (
        ImportRow.objects.select_for_update()
        .select_related("goodreads_import__user")
        .get(pk=row_id, goodreads_import=goodreads_import)
    )
    if row.state != State.UNMATCHED:
        raise RowNotResolvableError("This row has already been handled.")
    return row


def _record(goodreads_import: GoodreadsImport, row: ImportRow) -> None:
    """Persist the row's new state and keep the import's counters consistent."""
    if goodreads_import.status == GoodreadsImport.Status.DONE:
        GoodreadsImport.objects.filter(pk=goodreads_import.pk).update(
            unmatched_count=F("unmatched_count") - 1,
            **{COUNTER[row.state]: F(COUNTER[row.state]) + 1},
        )
        if row.state in DONE_STATES:
            row.delete()
        else:
            row.save()
    else:
        row.save()
        refresh_counts(goodreads_import)
        goodreads_import.save()
    goodreads_import.refresh_from_db()


@transaction.atomic
def resolve_row(goodreads_import: GoodreadsImport, row_id: int, book: Book) -> ImportRow:
    """Apply the reader's chosen book to an unmatched row. Returns the row (possibly
    already deleted from the database, with its final state and note)."""
    row = _locked_unmatched(row_id, goodreads_import)
    row.match_method = ImportRow.MatchMethod.MANUAL
    row.note = ""  # the old "why it didn't match" no longer applies
    apply_match(row, book)
    _record(goodreads_import, row)
    return row


@transaction.atomic
def dismiss_row(goodreads_import: GoodreadsImport, row_id: int) -> ImportRow:
    row = _locked_unmatched(row_id, goodreads_import)
    row.state = State.DISMISSED
    row.note = "Dismissed."
    _record(goodreads_import, row)
    return row

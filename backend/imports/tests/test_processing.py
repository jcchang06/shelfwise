"""Time-bounded, resumable batches; pausing; finishing; the lock (I-2)."""

import itertools

import pytest
from django.core.cache import cache

from catalog.tests.factories import AuthorFactory, BookFactory
from imports import processing
from imports.matching import Match, MatchPausedError
from imports.models import GoodreadsImport, ImportRow
from imports.processing import ImportBusyError, process_import_batch

from .helpers import make_import, make_row

pytestmark = pytest.mark.django_db

Status = GoodreadsImport.Status
State = ImportRow.State


@pytest.fixture
def catalog_books():
    """Books the rows match from the catalog by title + author (no HTTP at all)."""
    author = AuthorFactory(name="Mara Vell")
    return [
        BookFactory(title=f"Synthetic Book {n}", authors=[author], isbn_13="") for n in range(1, 6)
    ]


def fake_clock(step: float):
    """A clock that advances `step` seconds every time it's read."""
    ticks = itertools.count()
    return lambda: next(ticks) * step


def test_processes_every_row_and_finishes(catalog_books, monkeypatch):
    imp = make_import()
    for n in range(1, 4):
        make_row(imp, n)
    make_row(imp, 4, title="Nothing Like It", author="")  # no author: unmatched, no HTTP

    result = process_import_batch(imp.pk, max_seconds=60)

    assert result.status == Status.DONE and result.finished_at is not None
    assert (result.processed_rows, result.created_count, result.unmatched_count) == (4, 3, 0 + 1)
    # Matched rows are deleted (PRD privacy); the unmatched row stays for I-4.
    assert list(result.rows.values_list("row_number", "state")) == [(4, State.UNMATCHED)]


def test_stops_at_the_time_limit_and_resumes(catalog_books):
    imp = make_import()
    for n in range(1, 6):
        make_row(imp, n)

    # Each clock read advances 1s; a 2.5s budget fits only a couple of rows.
    first = process_import_batch(imp.pk, max_seconds=2.5, clock=fake_clock(1))
    assert first.status == Status.RUNNING
    assert 0 < first.processed_rows < 5

    second = process_import_batch(imp.pk, max_seconds=60)
    assert second.status == Status.DONE and second.created_count == 5


def test_pause_leaves_the_row_pending(catalog_books, monkeypatch):
    imp = make_import()
    make_row(imp, 1)
    make_row(imp, 2)

    def paused(row, prefetched):
        raise MatchPausedError("The import's Google budget (600 a day) is used up.")

    monkeypatch.setattr(processing, "match_row", paused)
    result = process_import_batch(imp.pk, max_seconds=60)

    assert result.status == Status.PAUSED and "600 a day" in result.error
    assert result.rows.filter(state=State.PENDING).count() == 2


def test_paused_import_resumes_later(catalog_books, monkeypatch):
    imp = make_import(status=Status.PAUSED, error="budget")
    make_row(imp, 1)
    result = process_import_batch(imp.pk, max_seconds=60)
    assert result.status == Status.DONE and result.error == ""


def test_one_bad_row_does_not_stop_the_import(catalog_books, monkeypatch):
    imp = make_import()
    make_row(imp, 1)
    make_row(imp, 2)
    real = processing.match_row

    def flaky(row, prefetched):
        if row.row_number == 1:
            raise RuntimeError("boom")
        return real(row, prefetched)

    monkeypatch.setattr(processing, "match_row", flaky)
    result = process_import_batch(imp.pk, max_seconds=60)

    assert result.status == Status.DONE
    assert (result.failed_count, result.created_count) == (1, 1)
    assert result.rows.get(row_number=1).note == "Something went wrong matching this row."


def test_failed_rows_from_parsing_are_kept_and_not_reprocessed(catalog_books, monkeypatch):
    imp = make_import()
    make_row(imp, 1, state=State.FAILED, note="No title")
    monkeypatch.setattr(processing, "match_row", lambda *a: pytest.fail("matched a failed row"))
    result = process_import_batch(imp.pk, max_seconds=60)
    assert result.status == Status.DONE and result.failed_count == 1
    assert result.rows.filter(state=State.FAILED).exists()


def test_unmatched_note_is_saved(monkeypatch):
    imp = make_import()
    make_row(imp, 1)
    monkeypatch.setattr(processing, "match_row", lambda row, p: Match(None, note="No luck."))
    result = process_import_batch(imp.pk, max_seconds=60)
    assert result.rows.get().note == "No luck."


def test_finished_imports_are_left_alone(monkeypatch):
    imp = make_import(status=Status.DONE)
    row = make_row(imp, 1)  # even a leftover pending row isn't touched
    monkeypatch.setattr(processing, "match_row", lambda *a: pytest.fail("reprocessed"))
    assert process_import_batch(imp.pk).status == Status.DONE
    row.refresh_from_db()
    assert row.state == State.PENDING


def test_a_second_caller_is_refused_while_a_batch_runs():
    imp = make_import()
    cache.add(processing._lock_key(imp.pk), "someone-else", timeout=60)
    with pytest.raises(ImportBusyError):
        process_import_batch(imp.pk)


def test_the_lock_is_released_after_a_batch(catalog_books):
    imp = make_import()
    make_row(imp, 1)
    process_import_batch(imp.pk, max_seconds=60)
    assert cache.get(processing._lock_key(imp.pk)) is None


def test_isbn_prefetch_happens_once_per_batch(catalog_books, monkeypatch):
    imp = make_import()
    for n in range(1, 4):
        make_row(imp, n)
    calls = []
    monkeypatch.setattr(processing, "prefetch_isbns", lambda rows: calls.append(len(rows)) or {})
    process_import_batch(imp.pk, max_seconds=60)
    assert calls == [3]


def test_rate_limit_ends_the_batch_without_pausing(catalog_books, monkeypatch):
    from imports.matching import MatchRetryLaterError

    imp = make_import()
    make_row(imp, 1)
    make_row(imp, 2)

    def rate_limited(row, prefetched):
        raise MatchRetryLaterError("slow down")

    monkeypatch.setattr(processing, "match_row", rate_limited)
    result = process_import_batch(imp.pk, max_seconds=60)

    assert result.status == Status.RUNNING and result.error == ""  # not paused
    assert result.rows.filter(state=State.PENDING).count() == 2

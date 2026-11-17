"""Page log rules in tracking.reading_logs (T-3), tested without HTTP."""

import datetime as dt

import pytest

from catalog.tests.factories import BookFactory
from tracking.models import ReadingLog, UserBook
from tracking.reading_logs import LogRuleError, log_pages, pages_logged, update_log
from tracking.services import default_dnf_page

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

S = UserBook.Status
TODAY = dt.date(2026, 11, 16)


def d(month: int, day: int, year: int = 2026) -> dt.date:
    return dt.date(year, month, day)


def log(user_book, pages=30, on=TODAY):
    entry, created, ub = log_pages(user_book.user, user_book.book, pages, on, today=TODAY)
    user_book.refresh_from_db()
    return entry, created


def errors_of(fn, *args, **kwargs) -> LogRuleError:
    with pytest.raises(LogRuleError) as exc_info:
        fn(*args, **kwargs)
    return exc_info.value


class TestLogPages:
    def test_creates_log_defaulting_to_today(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        entry, created, _ = log_pages(ub.user, ub.book, 42, today=TODAY)
        assert created
        assert (entry.log_date, entry.pages_read) == (TODAY, 42)

    def test_same_day_adds_to_existing_row(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        first, created_first = log(ub, 30)
        second, created_second = log(ub, 12)
        assert (created_first, created_second) == (True, False)
        assert second.pk == first.pk and second.pages_read == 42
        assert ReadingLog.objects.count() == 1

    def test_different_days_are_separate_rows(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        log(ub, 10, d(11, 14))
        log(ub, 10, d(11, 15))
        assert ReadingLog.objects.count() == 2

    def test_book_must_be_on_my_shelf(self):
        other_users_entry = UserBookFactory()
        book = BookFactory()
        err = errors_of(log_pages, other_users_entry.user, book, 10, today=TODAY)
        assert err.errors == {"book_id": "Add this book to your shelf first."}

    def test_book_on_someone_elses_shelf_only_is_rejected(self):
        theirs = UserBookFactory()
        mine = UserBookFactory()
        err = errors_of(log_pages, mine.user, theirs.book, 10, today=TODAY)
        assert "book_id" in err.errors

    def test_future_date_rejected(self):
        ub = UserBookFactory(status=S.READING)
        err = errors_of(log_pages, ub.user, ub.book, 10, TODAY + dt.timedelta(days=1), today=TODAY)
        assert set(err.errors) == {"log_date"}

    def test_cap_applies_to_day_total_after_adding(self, settings):
        settings.MAX_PAGES_PER_DAY = 100
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        log(ub, 60)
        err = errors_of(log_pages, ub.user, ub.book, 41, today=TODAY)
        assert set(err.errors) == {"pages_read"} and "101" in err.errors["pages_read"]
        assert ReadingLog.objects.get().pages_read == 60  # unchanged

    def test_exactly_the_cap_is_allowed(self, settings):
        settings.MAX_PAGES_PER_DAY = 100
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        assert log(ub, 100)[0].pages_read == 100


class TestShelfStatus:
    def test_want_to_read_moves_to_reading_starting_on_log_date(self):
        ub = UserBookFactory(status=S.WANT_TO_READ)
        log(ub, 20, d(11, 10))
        assert ub.status == S.READING and ub.started_at == d(11, 10)

    def test_want_to_read_with_start_keeps_it_unless_backfilled(self):
        ub = UserBookFactory(status=S.WANT_TO_READ, started_at=d(11, 5))
        log(ub, 20, d(11, 10))
        assert ub.status == S.READING and ub.started_at == d(11, 5)

    @pytest.mark.parametrize("status", [S.READING, S.FINISHED])
    def test_other_statuses_unchanged(self, status):
        ub = UserBookFactory(status=status, started_at=d(11, 1), finished_at=d(11, 12))
        log(ub, 20, d(11, 5))
        assert ub.status == status

    def test_dnf_book_can_be_backfilled_without_resuming(self):
        ub = UserBookFactory(dnf=True, started_at=d(10, 1))
        log(ub, 20, d(10, 20))
        assert ub.status == S.DNF and ub.dnf_reason  # still DNF, fields intact

    def test_no_start_date_is_not_invented_for_reading(self):
        ub = UserBookFactory(status=S.READING, started_at=None)
        log(ub, 20, d(11, 10))
        assert ub.started_at is None


class TestBackfill:
    def test_first_read_backfill_moves_started_at(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 10))
        log(ub, 25, d(11, 3))
        assert ub.started_at == d(11, 3)

    def test_finished_first_read_backfill_moves_started_at(self):
        # finished_at is this read's own finish (start <= finish), not a previous read's.
        ub = UserBookFactory(
            status=S.FINISHED, started_at=d(11, 10), finished_at=d(11, 14), rating=4
        )
        log(ub, 25, d(11, 3))
        assert ub.started_at == d(11, 3) and ub.finished_at == d(11, 14)

    def test_reread_backfill_before_old_finish_does_not_move_started_at(self):
        # First read finished 2025-03-09; the re-read started 2026-11-01.
        ub = UserBookFactory(
            status=S.READING, started_at=d(11, 1), finished_at=d(3, 9, 2025), rating=5
        )
        log(ub, 25, d(3, 1, 2025))  # a day from the first read
        assert ub.started_at == d(11, 1)

    def test_reread_backfill_on_the_old_finish_day_does_not_move_started_at(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1), finished_at=d(3, 9, 2025))
        log(ub, 25, d(3, 9, 2025))
        assert ub.started_at == d(11, 1)

    def test_reread_backfill_after_old_finish_moves_started_at(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1), finished_at=d(3, 9, 2025))
        log(ub, 25, d(10, 28))
        assert ub.started_at == d(10, 28)

    def test_later_log_never_moves_started_at_forward(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1))
        log(ub, 25, d(11, 15))
        assert ub.started_at == d(11, 1)


class TestUpdateLog:
    def test_sets_pages_not_adds(self):
        entry = ReadingLogFactory(pages_read=30, log_date=d(11, 10))
        UserBookFactory(user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 1))
        updated, _ = update_log(entry, {"pages_read": 12}, today=TODAY)
        assert updated.pages_read == 12

    def test_move_to_free_day(self):
        entry = ReadingLogFactory(log_date=d(11, 10))
        UserBookFactory(user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 1))
        updated, _ = update_log(entry, {"log_date": d(11, 11)}, today=TODAY)
        assert updated.log_date == d(11, 11)

    def test_move_onto_taken_day_reports_conflict(self):
        entry = ReadingLogFactory(log_date=d(11, 10))
        taken = ReadingLogFactory(user=entry.user, book=entry.book, log_date=d(11, 11))
        UserBookFactory(user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 1))
        err = errors_of(update_log, entry, {"log_date": d(11, 11)}, today=TODAY)
        assert err.conflict_id == taken.pk and set(err.errors) == {"log_date"}
        entry.refresh_from_db()
        assert entry.log_date == d(11, 10)

    def test_same_day_for_another_book_is_not_a_conflict(self):
        entry = ReadingLogFactory(log_date=d(11, 10))
        ReadingLogFactory(user=entry.user, log_date=d(11, 11))  # different book
        UserBookFactory(user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 1))
        assert update_log(entry, {"log_date": d(11, 11)}, today=TODAY)[0].log_date == d(11, 11)

    def test_patch_date_backfills_started_at(self):
        entry = ReadingLogFactory(log_date=d(11, 10))
        ub = UserBookFactory(
            user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 10)
        )
        update_log(entry, {"log_date": d(11, 4)}, today=TODAY)
        ub.refresh_from_db()
        assert ub.started_at == d(11, 4)

    def test_patch_date_later_keeps_started_at(self):
        entry = ReadingLogFactory(log_date=d(11, 4))
        ub = UserBookFactory(
            user=entry.user, book=entry.book, status=S.READING, started_at=d(11, 4)
        )
        update_log(entry, {"log_date": d(11, 9)}, today=TODAY)
        ub.refresh_from_db()
        assert ub.started_at == d(11, 4)

    def test_patch_never_changes_status(self):
        entry = ReadingLogFactory(log_date=d(11, 10))
        ub = UserBookFactory(user=entry.user, book=entry.book, status=S.WANT_TO_READ)
        update_log(entry, {"pages_read": 5, "log_date": d(11, 9)}, today=TODAY)
        ub.refresh_from_db()
        assert ub.status == S.WANT_TO_READ

    @pytest.mark.parametrize(
        ("changes", "field"),
        [
            ({"log_date": TODAY + dt.timedelta(days=1)}, "log_date"),
            ({"pages_read": 2001}, "pages_read"),
        ],
    )
    def test_validation(self, changes, field):
        entry = ReadingLogFactory(log_date=d(11, 10))
        UserBookFactory(user=entry.user, book=entry.book, status=S.READING)
        assert set(errors_of(update_log, entry, changes, today=TODAY).errors) == {field}

    def test_log_without_shelf_entry_can_still_be_edited(self):
        entry = ReadingLogFactory(log_date=d(11, 10))  # e.g. created in the admin
        updated, user_book = update_log(entry, {"pages_read": 3}, today=TODAY)
        assert updated.pages_read == 3 and user_book is None

    def test_unknown_field_is_a_programming_error(self):
        with pytest.raises(ValueError):
            update_log(ReadingLogFactory(), {"book": 1}, today=TODAY)


class TestCurrentRead:
    def test_pages_logged_counts_only_logs_since_started_at(self):
        ub = UserBookFactory(status=S.READING, started_at=d(11, 1), finished_at=d(3, 9, 2025))
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(3, 1, 2025), pages_read=300)
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(11, 1), pages_read=20)
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(11, 2), pages_read=15)
        assert pages_logged(ub) == 35

    def test_without_started_at_every_log_counts(self):
        ub = UserBookFactory(status=S.READING, started_at=None)
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(1, 1, 2020), pages_read=10)
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(11, 1), pages_read=10)
        assert pages_logged(ub) == 20

    def test_dnf_default_counts_only_the_current_read(self):
        ub = UserBookFactory(
            status=S.READING,
            started_at=d(11, 1),
            finished_at=d(3, 9, 2025),
            book=BookFactory(page_count=400),
        )
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(3, 1, 2025), pages_read=390)
        ReadingLogFactory(user=ub.user, book=ub.book, log_date=d(11, 3), pages_read=50)
        assert default_dnf_page(ub) == 50

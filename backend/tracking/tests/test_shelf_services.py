"""Shelf rules in tracking.services (T-2, T-4, T-6), tested without HTTP."""

import datetime as dt

import pytest

from catalog.tests.factories import BookFactory
from tracking.models import UserBook
from tracking.services import ShelfRuleError, apply_shelf_changes, default_dnf_page

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

S = UserBook.Status
R = UserBook.DnfReason
TODAY = dt.date(2026, 11, 16)
EARLIER = dt.date(2026, 10, 1)
FIRST_START = dt.date(2025, 2, 20)  # the first read, before a re-read
OLD_FINISH = dt.date(2025, 3, 9)


def apply(user_book, **changes):
    apply_shelf_changes(user_book, changes, today=TODAY)
    user_book.save()  # also proves the result satisfies the DB constraints
    user_book.refresh_from_db()
    return user_book


def rule_errors(user_book, **changes) -> dict[str, str]:
    with pytest.raises(ShelfRuleError) as exc_info:
        apply_shelf_changes(user_book, changes, today=TODAY)
    return exc_info.value.errors


def finished_book(**kwargs):
    return UserBookFactory(
        status=S.FINISHED, started_at=FIRST_START, finished_at=OLD_FINISH, rating=5, **kwargs
    )


def dnf_book(**kwargs):
    return UserBookFactory(
        status=S.DNF, dnf_page=120, dnf_at=EARLIER, dnf_reason=R.PACING, dnf_note="slow", **kwargs
    )


class TestToReading:
    def test_sets_started_at_when_empty(self):
        ub = apply(UserBookFactory(), status=S.READING)
        assert ub.status == S.READING and ub.started_at == TODAY

    def test_keeps_existing_started_at(self):
        ub = apply(UserBookFactory(started_at=EARLIER), status=S.READING)
        assert ub.started_at == EARLIER

    def test_sent_date_wins(self):
        ub = apply(UserBookFactory(), status=S.READING, started_at=EARLIER)
        assert ub.started_at == EARLIER


class TestToFinished:
    def test_sets_finished_at_today(self):
        ub = apply(UserBookFactory(status=S.READING, started_at=EARLIER), status=S.FINISHED)
        assert ub.finished_at == TODAY

    def test_sent_date_wins(self):
        ub = apply(UserBookFactory(status=S.READING), status=S.FINISHED, finished_at=EARLIER)
        assert ub.finished_at == EARLIER

    def test_rate_in_the_same_request(self):
        ub = apply(
            UserBookFactory(status=S.READING), status=S.FINISHED, rating=4, review="Loved it"
        )
        assert (ub.rating, ub.review) == (4, "Loved it")

    def test_reread_finished_again_gets_new_date(self):
        ub = finished_book()
        apply(ub, status=S.READING)
        ub = apply(ub, status=S.FINISHED)
        assert ub.finished_at == TODAY

    def test_reread_finished_again_with_sent_date(self):
        ub = finished_book()
        apply(ub, status=S.READING, started_at=dt.date(2026, 11, 1))
        ub = apply(ub, status=S.FINISHED, finished_at=dt.date(2026, 11, 10))
        assert ub.finished_at == dt.date(2026, 11, 10)

    def test_editing_a_finished_book_keeps_its_date(self):
        ub = apply(finished_book(), review="Even better the second time")
        assert ub.finished_at == OLD_FINISH


class TestLeavingFinished:
    @pytest.mark.parametrize("new_status", [S.READING, S.WANT_TO_READ])
    def test_reread_keeps_rating_and_finished_at(self, new_status):
        ub = apply(finished_book(), status=new_status)
        assert ub.status == new_status
        assert ub.rating == 5 and ub.finished_at == OLD_FINISH

    def test_reread_starts_today(self):
        # finished -> reading is a new read, so started_at moves to today even though the
        # first read's start is already set.
        ub = apply(finished_book(), status=S.READING)
        assert ub.started_at == TODAY

    def test_reread_sent_start_wins(self):
        ub = apply(finished_book(), status=S.READING, started_at=EARLIER)
        assert ub.started_at == EARLIER

    def test_finished_to_want_to_read_keeps_started_at(self):
        # Only entering `reading` touches started_at.
        ub = apply(finished_book(), status=S.WANT_TO_READ)
        assert ub.started_at == FIRST_START

    def test_full_reread_cycle_dates(self):
        ub = finished_book()
        apply(ub, status=S.READING, started_at=dt.date(2026, 11, 1))
        ub = apply(ub, status=S.FINISHED)
        assert (ub.started_at, ub.finished_at, ub.rating) == (dt.date(2026, 11, 1), TODAY, 5)

    def test_reread_can_send_new_start_after_old_finish(self):
        # finished_at (2025) is older than the new start; that's fine while not finished.
        ub = apply(finished_book(), status=S.READING, started_at=TODAY)
        assert ub.started_at == TODAY and ub.finished_at == OLD_FINISH

    def test_to_dnf_clears_rating_keeps_finished_at(self):
        ub = apply(finished_book(), status=S.DNF, dnf_reason=R.CONTENT)
        assert ub.rating is None
        assert ub.finished_at == OLD_FINISH


class TestToDnf:
    def test_requires_reason(self):
        errors = rule_errors(UserBookFactory(status=S.READING), status=S.DNF)
        assert set(errors) == {"dnf_reason"}

    def test_defaults(self):
        ub = UserBookFactory(status=S.READING)
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=40, log_date=EARLIER)
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=35, log_date=TODAY)

        ub = apply(ub, status=S.DNF, dnf_reason=R.WRITING_STYLE)

        assert ub.dnf_at == TODAY
        assert ub.dnf_page == 75
        assert ub.dnf_note == ""

    def test_sent_values_win(self):
        ub = UserBookFactory(status=S.READING)
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=40)
        ub = apply(
            ub,
            status=S.DNF,
            dnf_reason=R.OTHER,
            dnf_page=12,
            dnf_at=EARLIER,
            dnf_note="Lost my copy",
        )
        assert (ub.dnf_page, ub.dnf_at, ub.dnf_note) == (12, EARLIER, "Lost my copy")

    def test_no_logs_means_no_default_page(self):
        ub = apply(UserBookFactory(status=S.READING), status=S.DNF, dnf_reason=R.PACING)
        assert ub.dnf_page is None

    def test_from_want_to_read_is_allowed(self):
        ub = apply(UserBookFactory(), status=S.DNF, dnf_reason=R.NOT_IN_THE_MOOD)
        assert ub.status == S.DNF

    def test_rating_null_with_dnf_is_fine(self):
        ub = apply(finished_book(), status=S.DNF, dnf_reason=R.PACING, rating=None)
        assert ub.rating is None

    def test_resent_old_rating_is_still_cleared(self):
        ub = apply(finished_book(), status=S.DNF, dnf_reason=R.PACING, rating=5)
        assert ub.rating is None

    def test_logs_are_kept(self):
        ub = UserBookFactory(status=S.READING)
        ReadingLogFactory(user=ub.user, book=ub.book)
        apply(ub, status=S.DNF, dnf_reason=R.PACING)
        assert ub.book.reading_logs.filter(user=ub.user).count() == 1


class TestEditingDnf:
    def test_change_reason_and_note(self):
        ub = apply(dnf_book(), dnf_reason=R.NOT_MY_GENRE, dnf_note="Not for me")
        assert (ub.dnf_reason, ub.dnf_note) == (R.NOT_MY_GENRE, "Not for me")
        assert ub.dnf_at == EARLIER  # not reset: the status didn't change

    def test_reason_cannot_be_blanked(self):
        assert set(rule_errors(dnf_book(), dnf_reason="")) == {"dnf_reason"}


class TestLeavingDnf:
    @pytest.mark.parametrize("new_status", [S.READING, S.WANT_TO_READ, S.FINISHED])
    def test_clears_every_dnf_field(self, new_status):
        ub = apply(dnf_book(), status=new_status)
        assert ub.status == new_status
        assert (ub.dnf_page, ub.dnf_at, ub.dnf_reason, ub.dnf_note) == (None, None, "", "")

    def test_resume_keeps_original_started_at(self):
        # dnf -> reading resumes the same read, so the start date stays.
        ub = apply(dnf_book(started_at=EARLIER), status=S.READING)
        assert ub.started_at == EARLIER

    def test_resume_without_a_start_date_starts_today(self):
        ub = apply(dnf_book(started_at=None), status=S.READING)
        assert ub.started_at == TODAY

    def test_resume_keeps_logs(self):
        ub = dnf_book()
        ReadingLogFactory(user=ub.user, book=ub.book)
        apply(ub, status=S.READING)
        assert ub.book.reading_logs.filter(user=ub.user).count() == 1

    def test_resending_empty_dnf_fields_is_fine(self):
        # A client PATCHing the whole object back with blanks shouldn't be rejected.
        ub = apply(dnf_book(), status=S.READING, dnf_reason="", dnf_page=None, dnf_note="")
        assert ub.dnf_reason == ""

    def test_dnf_to_finished_can_be_rated(self):
        ub = apply(dnf_book(), status=S.FINISHED, rating=3)
        assert ub.rating == 3


class TestRatingRules:
    @pytest.mark.parametrize("status", [S.WANT_TO_READ, S.READING, S.DNF])
    def test_cannot_set_rating_unless_finished(self, status):
        ub = UserBookFactory(status=status, dnf_reason=R.PACING if status == S.DNF else "")
        assert set(rule_errors(ub, rating=4)) == {"rating"}

    def test_cannot_change_kept_rating_during_reread(self):
        ub = apply(finished_book(), status=S.READING)
        assert set(rule_errors(ub, rating=3)) == {"rating"}

    def test_cannot_clear_kept_rating_during_reread(self):
        ub = apply(finished_book(), status=S.READING)
        assert set(rule_errors(ub, rating=None)) == {"rating"}

    def test_resending_unchanged_rating_is_fine(self):
        ub = apply(finished_book(), status=S.READING)
        ub = apply(ub, rating=5, review="Re-reading")
        assert ub.rating == 5

    def test_finished_book_can_change_or_clear_rating(self):
        ub = apply(finished_book(), rating=2)
        assert ub.rating == 2
        assert apply(ub, rating=None).rating is None

    def test_rating_and_finish_in_one_request(self):
        ub = apply(UserBookFactory(status=S.READING), rating=5, status=S.FINISHED)
        assert ub.rating == 5


class TestFieldRules:
    @pytest.mark.parametrize(
        "field,value",
        [("dnf_reason", R.PACING), ("dnf_page", 10), ("dnf_at", EARLIER), ("dnf_note", "x")],
    )
    def test_dnf_fields_rejected_when_not_dnf(self, field, value):
        assert set(rule_errors(UserBookFactory(status=S.READING), **{field: value})) == {field}

    def test_dnf_fields_rejected_when_leaving_dnf(self):
        errors = rule_errors(dnf_book(), status=S.READING, dnf_note="still here?")
        assert set(errors) == {"dnf_note"}

    @pytest.mark.parametrize("field", ["started_at", "finished_at"])
    def test_future_dates_rejected(self, field):
        ub = UserBookFactory(status=S.FINISHED)
        tomorrow = TODAY + dt.timedelta(days=1)
        assert field in rule_errors(ub, **{field: tomorrow})

    def test_future_dnf_date_rejected(self):
        errors = rule_errors(
            UserBookFactory(status=S.READING),
            status=S.DNF,
            dnf_reason=R.PACING,
            dnf_at=TODAY + dt.timedelta(days=1),
        )
        assert set(errors) == {"dnf_at"}

    def test_today_is_allowed(self):
        assert apply(UserBookFactory(), status=S.READING, started_at=TODAY).started_at == TODAY

    def test_start_after_finish_rejected_for_finished_book(self):
        ub = UserBookFactory(status=S.READING)
        errors = rule_errors(ub, status=S.FINISHED, started_at=TODAY, finished_at=EARLIER)
        assert set(errors) == {"started_at"}

    def test_dnf_page_cannot_exceed_page_count(self):
        ub = UserBookFactory(status=S.READING, book=BookFactory(page_count=300))
        errors = rule_errors(ub, status=S.DNF, dnf_reason=R.PACING, dnf_page=301)
        assert errors == {"dnf_page": "This book has only 300 pages."}

    def test_dnf_page_unchecked_without_page_count(self):
        ub = UserBookFactory(status=S.READING, book=BookFactory(page_count=None))
        assert apply(ub, status=S.DNF, dnf_reason=R.PACING, dnf_page=5000).dnf_page == 5000

    def test_reports_every_error_at_once_and_leaves_book_unchanged(self):
        ub = UserBookFactory(status=S.READING)
        errors = rule_errors(ub, rating=4, dnf_note="x", started_at=TODAY + dt.timedelta(days=3))
        assert set(errors) == {"rating", "dnf_note", "started_at"}
        assert ub.rating is None and ub.dnf_note == ""

    def test_unknown_field_is_a_programming_error(self):
        with pytest.raises(ValueError):
            apply_shelf_changes(UserBookFactory(), {"user": 1}, today=TODAY)


class TestDefaultDnfPage:
    def test_only_counts_this_users_logs_for_this_book(self):
        ub = UserBookFactory()
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=20)
        ReadingLogFactory(book=ub.book, pages_read=500)  # someone else
        ReadingLogFactory(user=ub.user, pages_read=500)  # another book
        assert default_dnf_page(ub) == 20

    def test_capped_at_page_count(self):
        ub = UserBookFactory(book=BookFactory(page_count=100))
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=150)
        assert default_dnf_page(ub) == 100

    def test_default_capped_when_marking_dnf(self):
        ub = UserBookFactory(status=S.READING, book=BookFactory(page_count=100))
        ReadingLogFactory(user=ub.user, book=ub.book, pages_read=150)
        assert apply(ub, status=S.DNF, dnf_reason=R.PACING).dnf_page == 100


def test_now_uses_local_date_by_default(settings, monkeypatch):
    # No `today` passed: the service uses Django's local date (TIME_ZONE).
    from django.utils import timezone

    monkeypatch.setattr(timezone, "localdate", lambda: TODAY)
    ub = UserBookFactory()
    apply_shelf_changes(ub, {"status": S.READING})
    assert ub.started_at == TODAY


def test_reread_finish_before_new_start_rejected():
    # Re-read started today (finished -> reading); finishing it on an earlier day is invalid.
    ub = UserBookFactory(
        status=S.FINISHED, started_at=FIRST_START, finished_at=OLD_FINISH, rating=5
    )
    apply(ub, status=S.READING)
    errors = rule_errors(ub, status=S.FINISHED, finished_at=dt.date(2026, 11, 10))
    assert set(errors) == {"started_at"}

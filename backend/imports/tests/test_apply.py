"""Applying matched rows to the shelf: create, re-import rules, existing entries (I-1, I-3)."""

import datetime as dt

import pytest
from django.utils import timezone

from catalog.tests.factories import BookFactory
from imports.apply import apply_match, placeholder_dnf_count
from imports.models import GoodreadsLink, ImportRow
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

from .helpers import make_import, make_row

pytestmark = pytest.mark.django_db

S = UserBook.Status
State = ImportRow.State
TODAY = dt.date(2026, 11, 16)


def apply(row, book):
    apply_match(row, book, today=TODAY)
    row.save()
    return row


class TestCreate:
    def test_finished_with_rating_date_and_review(self):
        row = make_row(
            make_import(),
            status=S.FINISHED,
            rating=5,
            date_read=dt.date(2024, 3, 9),
            date_added=dt.date(2024, 1, 2),
            review="Loved it.",
        )
        book = BookFactory()
        apply(row, book)

        entry = UserBook.objects.get(user=row.goodreads_import.user, book=book)
        assert (entry.status, entry.rating, entry.finished_at, entry.review) == (
            S.FINISHED,
            5,
            dt.date(2024, 3, 9),
            "Loved it.",
        )
        assert entry.started_at is None  # Goodreads has no start date: none invented
        assert timezone.localtime(entry.created_at).date() == dt.date(2024, 1, 2)  # "Added"
        assert row.state == State.CREATED and row.user_book == entry and row.book == book
        link = GoodreadsLink.objects.get(user=entry.user, goodreads_book_id=row.goodreads_book_id)
        assert link.user_book == entry and link.synced_at == entry.updated_at

    def test_finished_without_a_date_stays_undated(self):
        row = make_row(make_import(), status=S.FINISHED)
        apply(row, BookFactory())
        assert UserBook.objects.get().finished_at is None  # not "today"

    def test_reading_gets_no_invented_start_date(self):
        row = make_row(make_import(), status=S.READING)
        apply(row, BookFactory())
        assert UserBook.objects.get().started_at is None

    def test_dnf_gets_reason_not_specified(self):
        row = make_row(make_import(), status=S.DNF, date_read=dt.date(2023, 11, 20))
        apply(row, BookFactory())
        entry = UserBook.objects.get()
        assert (entry.status, entry.dnf_reason, entry.dnf_note, entry.dnf_at, entry.dnf_page) == (
            S.DNF,
            UserBook.DnfReason.NOT_SPECIFIED,
            "",
            dt.date(2023, 11, 20),
            None,
        )
        assert placeholder_dnf_count(entry.user) == 1

    def test_placeholder_count_drops_once_a_real_reason_is_set(self):
        row = make_row(make_import(), status=S.DNF)
        apply(row, BookFactory())
        UserBook.objects.update(dnf_reason=UserBook.DnfReason.PACING)
        assert placeholder_dnf_count(row.goodreads_import.user) == 0

    def test_placeholder_count_ignores_dnfs_added_by_hand(self):
        entry = UserBookFactory(status=S.DNF, dnf_reason=UserBook.DnfReason.NOT_SPECIFIED)
        assert placeholder_dnf_count(entry.user) == 0

    def test_fills_the_books_series_if_empty(self):
        book = BookFactory(series_name="")
        row = make_row(make_import(), series_name="Lanternfall", series_number=1)
        apply(row, book)
        book.refresh_from_db()
        assert (book.series_name, book.series_number) == ("Lanternfall", 1)

    def test_shelf_rule_violation_fails_the_row(self):
        row = make_row(make_import(), status=S.FINISHED, date_read=dt.date(2999, 1, 1))
        apply(row, BookFactory())
        assert row.state == State.FAILED and "future" in row.note
        assert not UserBook.objects.exists()


class TestReimport:
    def first_import(self, **row_fields):
        row = make_row(make_import(), status=S.FINISHED, rating=3, **row_fields)
        book = BookFactory()
        apply(row, book)
        return row.goodreads_import.user, book, row.goodreads_book_id

    def test_unchanged_entry_is_updated_from_goodreads(self):
        user, book, goodreads_id = self.first_import()
        again = make_row(
            make_import(user), goodreads_book_id=goodreads_id, status=S.FINISHED, rating=5
        )
        apply(again, book)

        assert again.state == State.UPDATED
        assert UserBook.objects.get().rating == 5
        assert UserBook.objects.count() == 1  # never a duplicate (I-3)

    def test_entry_changed_in_shelfwise_is_skipped(self):
        user, book, goodreads_id = self.first_import()
        entry = UserBook.objects.get()
        entry.review = "My own notes"
        entry.save()  # updated_at moves past the link's synced_at

        again = make_row(
            make_import(user), goodreads_book_id=goodreads_id, status=S.FINISHED, rating=1
        )
        apply(again, book)

        assert again.state == State.SKIPPED
        assert "Changed in Shelfwise since the last import" in again.note
        entry.refresh_from_db()
        assert (entry.rating, entry.review) == (3, "My own notes")

    def test_updating_refreshes_synced_at(self):
        user, book, goodreads_id = self.first_import()
        again = make_row(
            make_import(user), goodreads_book_id=goodreads_id, status=S.FINISHED, rating=4
        )
        apply(again, book)
        link = GoodreadsLink.objects.get()
        assert link.synced_at == UserBook.objects.get().updated_at


class TestExistingEntry:
    def test_hand_added_entry_is_linked_and_only_empty_fields_filled(self):
        entry = UserBookFactory(status=S.FINISHED, rating=None, review="", finished_at=None)
        row = make_row(
            make_import(entry.user),
            status=S.FINISHED,
            rating=4,
            review="Great",
            date_read=dt.date(2025, 2, 1),
        )
        apply(row, entry.book)

        entry.refresh_from_db()
        assert (entry.rating, entry.review, entry.finished_at) == (4, "Great", dt.date(2025, 2, 1))
        assert row.state == State.UPDATED and "filled in review, rating, finished_at" in row.note
        assert GoodreadsLink.objects.get().user_book == entry

    def test_existing_values_and_status_are_never_overwritten(self):
        entry = UserBookFactory(status=S.READING, review="Mine")
        row = make_row(make_import(entry.user), status=S.FINISHED, rating=5, review="Theirs")
        apply(row, entry.book)
        entry.refresh_from_db()
        assert (entry.status, entry.review, entry.rating) == (S.READING, "Mine", None)
        assert row.state == State.SKIPPED and "nothing to fill in" in row.note

    def test_two_goodreads_editions_share_one_entry(self):
        imp = make_import()
        book = BookFactory()
        first = make_row(imp, 1, status=S.FINISHED, rating=4)
        second = make_row(imp, 2, status=S.FINISHED, rating=4)
        apply(first, book)
        apply(second, book)
        assert UserBook.objects.count() == 1
        assert GoodreadsLink.objects.count() == 2

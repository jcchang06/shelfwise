import datetime as dt

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from accounts.tests.factories import UserFactory
from catalog.tests.factories import BookFactory
from tracking.models import ReadingLog, UserBook

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db


class TestUserBook:
    def test_defaults_to_want_to_read(self):
        assert UserBookFactory().status == UserBook.Status.WANT_TO_READ

    def test_one_row_per_user_and_book(self):
        ub = UserBookFactory()
        with pytest.raises(IntegrityError):
            UserBookFactory(user=ub.user, book=ub.book)

    def test_same_book_on_two_users_shelves(self):
        book = BookFactory()
        UserBookFactory(book=book)
        UserBookFactory(book=book)
        assert book.user_books.count() == 2

    @pytest.mark.parametrize("rating", [1, 5, None])
    def test_valid_ratings(self, rating):
        assert UserBookFactory(finished=True, rating=rating).rating == rating

    @pytest.mark.parametrize("rating", [0, 6])
    def test_rating_outside_1_to_5_rejected(self, rating):
        with pytest.raises(IntegrityError):
            UserBookFactory(finished=True, rating=rating)

    def test_dnf_with_reason(self):
        ub = UserBookFactory(dnf=True)
        assert ub.dnf_reason == UserBook.DnfReason.PACING
        assert ub.dnf_page == 80

    def test_dnf_without_reason_rejected(self):
        with pytest.raises(IntegrityError):
            UserBookFactory(dnf=True, dnf_reason="")

    def test_dnf_reasons_match_settings_weights(self, settings):
        # The recommender (R-5) looks weights up by reason, so every reason needs one.
        assert set(UserBook.DnfReason.values) == set(settings.DNF_REASON_WEIGHTS)

    def test_dnf_can_move_back_to_reading(self):
        ub = UserBookFactory(dnf=True)
        ub.status = UserBook.Status.READING
        ub.save()
        ub.refresh_from_db()
        assert ub.status == UserBook.Status.READING

    def test_deleting_user_removes_shelf(self):
        ub = UserBookFactory()
        ub.user.delete()
        assert not UserBook.objects.filter(pk=ub.pk).exists()

    def test_book_on_a_shelf_cannot_be_deleted(self):
        ub = UserBookFactory()
        with pytest.raises(ProtectedError):
            ub.book.delete()

    def test_str(self):
        ub = UserBookFactory.build(
            user=UserFactory.build(email="a@example.com"), book=BookFactory.build(title="Dune")
        )
        assert str(ub) == "a@example.com – Dune (want_to_read)"


class TestReadingLog:
    def test_one_log_per_book_per_day(self):
        log = ReadingLogFactory()
        with pytest.raises(IntegrityError):
            ReadingLogFactory(user=log.user, book=log.book, log_date=log.log_date)

    def test_same_book_on_different_days(self):
        log = ReadingLogFactory(log_date=dt.date(2026, 11, 1))
        ReadingLogFactory(user=log.user, book=log.book, log_date=dt.date(2026, 11, 2))
        assert ReadingLog.objects.filter(user=log.user).count() == 2

    def test_zero_pages_rejected(self):
        with pytest.raises(IntegrityError):
            ReadingLogFactory(pages_read=0)

    def test_logs_survive_dnf(self):
        ub = UserBookFactory(status=UserBook.Status.READING)
        ReadingLogFactory(user=ub.user, book=ub.book)
        ub.status, ub.dnf_reason = UserBook.Status.DNF, UserBook.DnfReason.CONTENT
        ub.save()
        assert ReadingLog.objects.filter(user=ub.user, book=ub.book).count() == 1

    def test_deleting_user_removes_logs(self):
        log = ReadingLogFactory()
        log.user.delete()
        assert not ReadingLog.objects.filter(pk=log.pk).exists()

    def test_str(self):
        log = ReadingLogFactory.build(
            user=UserFactory.build(email="a@example.com"),
            book=BookFactory.build(title="Dune"),
            log_date=dt.date(2026, 11, 15),
            pages_read=30,
        )
        assert str(log) == "a@example.com – Dune: 30 pages on 2026-11-15"

"""Dashboard stats in tracking.stats (T-5), tested without HTTP."""

import datetime as dt

import pytest

from accounts.tests.factories import UserFactory
from catalog.tests.factories import BookFactory
from tracking import stats
from tracking.models import UserBook

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

S = UserBook.Status
R = UserBook.DnfReason
YEAR = 2026


def d(month: int, day: int, year: int = YEAR) -> dt.date:
    return dt.date(year, month, day)


@pytest.fixture
def user():
    return UserFactory()


def finished(user, on: dt.date | None, rating=None, genres=None, status=S.FINISHED):
    return UserBookFactory(
        user=user,
        status=status,
        finished_at=on,
        rating=rating,
        book=BookFactory(genres=genres if genres is not None else []),
    )


def dnf(user, on: dt.date | None, genres=None):
    return UserBookFactory(
        user=user,
        status=S.DNF,
        dnf_reason=R.PACING,
        dnf_at=on,
        book=BookFactory(genres=genres if genres is not None else []),
    )


class TestPagesPerMonth:
    def test_twelve_months_with_zeros(self, user):
        ub = UserBookFactory(user=user, status=S.READING)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(3, 2), pages_read=40)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(3, 20), pages_read=10)

        rows = stats.pages_per_month(user, YEAR)

        assert [r["month"] for r in rows] == [f"2026-{m:02d}" for m in range(1, 13)]
        assert rows[2] == {"month": "2026-03", "pages": 50, "dnf_pages": 0}
        assert sum(r["pages"] for r in rows) == 50

    def test_dnf_pages_are_a_subset_of_pages(self, user):
        reading = UserBookFactory(user=user, status=S.READING)
        stopped = dnf(user, d(5, 30))
        ReadingLogFactory(user=user, book=reading.book, log_date=d(5, 1), pages_read=70)
        ReadingLogFactory(user=user, book=stopped.book, log_date=d(5, 2), pages_read=30)

        may = stats.pages_per_month(user, YEAR)[4]

        assert may == {"month": "2026-05", "pages": 100, "dnf_pages": 30}

    def test_year_boundaries(self, user):
        ub = UserBookFactory(user=user, status=S.READING)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(12, 31, 2025), pages_read=5)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(1, 1), pages_read=7)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(12, 31), pages_read=11)
        ReadingLogFactory(user=user, book=ub.book, log_date=d(1, 1, 2027), pages_read=13)

        rows = stats.pages_per_month(user, YEAR)

        assert rows[0]["pages"] == 7 and rows[11]["pages"] == 11
        assert sum(r["pages"] for r in rows) == 18

    def test_only_my_logs(self, user):
        ReadingLogFactory(log_date=d(2, 1), pages_read=500)  # another user
        assert sum(r["pages"] for r in stats.pages_per_month(user, YEAR)) == 0


class TestBooksPerYear:
    def test_finished_and_dnf_by_their_own_dates(self, user):
        finished(user, d(6, 1, 2025))
        finished(user, d(1, 15))
        finished(user, d(11, 2))
        dnf(user, d(3, 3))

        assert stats.books_per_year(user) == [
            {"year": 2025, "finished": 1, "dnf": 0},
            {"year": 2026, "finished": 2, "dnf": 1},
        ]

    def test_undated_entries_go_in_a_final_null_year_row(self, user):
        # e.g. a Goodreads import with a shelf but no read dates
        finished(user, d(4, 1))
        finished(user, None)
        finished(user, None)
        dnf(user, None)

        rows = stats.books_per_year(user)

        assert rows == [
            {"year": 2026, "finished": 1, "dnf": 0},
            {"year": None, "finished": 2, "dnf": 1},
        ]
        # Totals reconcile with the shelf.
        assert (
            sum(r["finished"] for r in rows)
            == UserBook.objects.filter(user=user, status=S.FINISHED).count()
        )
        assert (
            sum(r["dnf"] for r in rows) == UserBook.objects.filter(user=user, status=S.DNF).count()
        )

    def test_no_null_row_when_everything_is_dated(self, user):
        finished(user, d(4, 1))
        assert all(r["year"] is not None for r in stats.books_per_year(user))

    def test_reread_in_progress_is_not_finished(self, user):
        # Status reading with a kept finished_at from the previous read.
        finished(user, d(3, 9, 2025), rating=5, status=S.READING)
        assert stats.books_per_year(user) == []

    def test_want_to_read_and_reading_ignored(self, user):
        UserBookFactory(user=user, status=S.WANT_TO_READ)
        UserBookFactory(user=user, status=S.READING)
        assert stats.books_per_year(user) == []

    def test_only_my_books(self, user):
        finished(UserFactory(), d(1, 1))
        assert stats.books_per_year(user) == []


class TestGenreMix:
    def test_counts_finished_and_dnf_separately(self, user):
        finished(user, d(2, 1), genres=["Science Fiction", "Space Opera"])
        finished(user, d(3, 1), genres=["Science Fiction"])
        dnf(user, d(4, 1), genres=["Science Fiction", "Romance"])

        assert stats.genre_mix(user, YEAR) == [
            {"genre": "Science Fiction", "finished": 2, "dnf": 1},
            {"genre": "Romance", "finished": 0, "dnf": 1},
            {"genre": "Space Opera", "finished": 1, "dnf": 0},
        ]

    def test_merges_case_and_uses_most_common_spelling(self, user):
        finished(user, d(1, 1), genres=["Science fiction"])
        finished(user, d(1, 2), genres=["Science Fiction"])
        finished(user, d(1, 3), genres=["Science Fiction"])
        assert stats.genre_mix(user, YEAR) == [
            {"genre": "Science Fiction", "finished": 3, "dnf": 0}
        ]

    def test_each_genre_once_per_book(self, user):
        finished(user, d(1, 1), genres=["Thrillers", "thrillers", " Thrillers "])
        assert stats.genre_mix(user, YEAR) == [{"genre": "Thrillers", "finished": 1, "dnf": 0}]

    def test_excluded_labels_case_insensitive(self, user):
        finished(user, d(1, 1), genres=["Fiction", "FICTION", "nonfiction", "Mystery"])
        assert stats.genre_mix(user, YEAR) == [{"genre": "Mystery", "finished": 1, "dnf": 0}]

    def test_excluded_labels_come_from_settings(self, user, settings):
        settings.STATS_EXCLUDED_GENRES = ["mystery"]
        finished(user, d(1, 1), genres=["Fiction", "Mystery"])
        assert stats.genre_mix(user, YEAR) == [{"genre": "Fiction", "finished": 1, "dnf": 0}]

    def test_top_eight_then_other(self, user):
        # Genre i appears on (12 - i) books, so the ranking is deterministic.
        for i in range(10):
            for n in range(12 - i):
                finished(user, d(1, 1 + n), genres=[f"Genre {i}"])

        rows = stats.genre_mix(user, YEAR)

        assert [r["genre"] for r in rows] == [f"Genre {i}" for i in range(8)] + ["Other"]
        assert rows[-1] == {"genre": "Other", "finished": (12 - 8) + (12 - 9), "dnf": 0}

    def test_no_other_row_when_eight_or_fewer(self, user):
        finished(user, d(1, 1), genres=["A", "B"])
        assert "Other" not in [r["genre"] for r in stats.genre_mix(user, YEAR)]

    def test_only_books_dated_in_the_year(self, user):
        finished(user, d(12, 31, 2025), genres=["Old"])
        finished(user, None, genres=["Undated"])
        dnf(user, d(1, 1, 2027), genres=["Future"])
        finished(user, d(6, 1), genres=["Current"])
        assert [r["genre"] for r in stats.genre_mix(user, YEAR)] == ["Current"]

    def test_reread_in_progress_not_counted(self, user):
        finished(user, d(2, 1), genres=["Horror"], status=S.READING)
        assert stats.genre_mix(user, YEAR) == []

    def test_books_without_genres_are_skipped(self, user):
        finished(user, d(1, 1), genres=[])
        assert stats.genre_mix(user, YEAR) == []


class TestRatingDistribution:
    def test_all_five_stars_with_zeros(self, user):
        finished(user, d(1, 1), rating=5)
        finished(user, d(1, 2), rating=5)
        finished(user, d(1, 3), rating=2)
        finished(user, d(1, 4), rating=None)

        assert stats.rating_distribution(user, YEAR) == [
            {"stars": 1, "books": 0},
            {"stars": 2, "books": 1},
            {"stars": 3, "books": 0},
            {"stars": 4, "books": 0},
            {"stars": 5, "books": 2},
        ]

    def test_reread_keeps_its_rating_in_the_year_it_was_finished(self, user):
        finished(user, d(8, 1), rating=4, status=S.READING)
        assert stats.rating_distribution(user, YEAR)[3] == {"stars": 4, "books": 1}

    def test_other_years_excluded(self, user):
        finished(user, d(12, 31, 2025), rating=5)
        assert sum(r["books"] for r in stats.rating_distribution(user, YEAR)) == 0


class TestStatsFor:
    def test_combines_sections_and_totals(self, user):
        reading = UserBookFactory(user=user, status=S.READING)
        ReadingLogFactory(user=user, book=reading.book, log_date=d(2, 1), pages_read=120)
        finished(user, d(2, 10), rating=5, genres=["Fantasy"])
        finished(user, d(3, 10), rating=4, genres=["Fantasy"])
        finished(user, d(3, 10, 2025), rating=1)  # other year
        dnf(user, d(4, 1))

        result = stats.stats_for(user, YEAR)

        assert result["year"] == YEAR
        assert result["totals"] == {"pages": 120, "finished": 2, "dnf": 1, "average_rating": 4.5}
        assert set(result) == {
            "year",
            "totals",
            "pages_per_month",
            "books_per_year",
            "genre_mix",
            "rating_distribution",
        }

    def test_empty_year(self, user):
        result = stats.stats_for(user, YEAR)
        assert result["totals"] == {"pages": 0, "finished": 0, "dnf": 0, "average_rating": None}
        assert result["books_per_year"] == [] and result["genre_mix"] == []

    def test_query_count_is_constant(self, user, django_assert_max_num_queries):
        for i in range(15):
            ub = finished(user, d(1 + i % 12, 1), rating=1 + i % 5, genres=[f"G{i % 4}"])
            ReadingLogFactory(user=user, book=ub.book, log_date=d(1 + i % 12, 2))
        with django_assert_max_num_queries(5):
            stats.stats_for(user, YEAR)

"""GET /api/stats/ (T-5). Counting rules are covered in test_stats.py."""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from tracking.models import UserBook

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

STATS = reverse("stats:stats")


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def test_requires_login(api_client):
    assert api_client.get(STATS).status_code == 401


def test_defaults_to_current_local_year(client):
    body = client.get(STATS).json()
    assert body["year"] == timezone.localdate().year
    assert body["pages_per_month"][0]["month"] == f"{timezone.localdate().year}-01"


def test_explicit_year(client, user):
    ub = UserBookFactory(
        user=user, status=UserBook.Status.FINISHED, finished_at=dt.date(2024, 5, 1)
    )
    ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2024, 5, 1), pages_read=77)
    body = client.get(STATS, {"year": 2024}).json()
    assert body["year"] == 2024
    assert body["totals"]["pages"] == 77 and body["totals"]["finished"] == 1


def test_response_shape(client):
    body = client.get(STATS).json()
    assert set(body) == {
        "year",
        "totals",
        "pages_per_month",
        "books_per_year",
        "genre_mix",
        "rating_distribution",
    }
    assert set(body["totals"]) == {"pages", "finished", "dnf", "average_rating"}


def test_only_my_numbers(client):
    other = UserFactory()
    ub = UserBookFactory(
        user=other, status=UserBook.Status.FINISHED, finished_at=timezone.localdate()
    )
    ReadingLogFactory(user=other, book=ub.book, log_date=timezone.localdate(), pages_read=500)
    body = client.get(STATS).json()
    assert body["totals"] == {"pages": 0, "finished": 0, "dnf": 0, "average_rating": None}
    assert body["books_per_year"] == []


def test_undated_row_serializes_as_null(client, user):
    UserBookFactory(user=user, status=UserBook.Status.FINISHED, finished_at=None)
    assert client.get(STATS).json()["books_per_year"] == [{"year": None, "finished": 1, "dnf": 0}]


@pytest.mark.parametrize("year", ["abc", "1899", "-2026", "2026.5", "99999"])
def test_bad_year_400(client, year):
    response = client.get(STATS, {"year": year})
    assert response.status_code == 400 and "year" in response.json()


def test_future_year_400(client):
    response = client.get(STATS, {"year": timezone.localdate().year + 1})
    assert response.status_code == 400


def test_empty_year_param_means_current_year(client):
    assert client.get(STATS, {"year": ""}).json()["year"] == timezone.localdate().year


def test_query_count(client, user, django_assert_max_num_queries):
    for i in range(10):
        ub = UserBookFactory(
            user=user, status=UserBook.Status.FINISHED, finished_at=timezone.localdate()
        )
        ReadingLogFactory(
            user=user, book=ub.book, log_date=timezone.localdate() - dt.timedelta(days=i)
        )
    with django_assert_max_num_queries(5):  # auth is forced, so only the stats queries
        client.get(STATS)

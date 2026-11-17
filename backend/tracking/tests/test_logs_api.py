"""Page log endpoints (T-3). Rule details are in test_reading_logs.py; these tests check
the HTTP contract, user isolation and that the rules are wired in."""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from catalog.tests.factories import BookFactory
from tracking.models import ReadingLog, UserBook

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

S = UserBook.Status
LOGS = reverse("logs:log-list")


def detail(log) -> str:
    return reverse("logs:log-detail", args=[log.pk])


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def reading(user):
    return UserBookFactory(user=user, status=S.READING, started_at=dt.date(2026, 11, 1))


def yesterday() -> dt.date:
    return timezone.localdate() - dt.timedelta(days=1)


class TestAuthAndIsolation:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("get", LOGS),
            ("post", LOGS),
            ("get", "/api/logs/1/"),
            ("patch", "/api/logs/1/"),
            ("delete", "/api/logs/1/"),
        ],
    )
    def test_anonymous_gets_401(self, api_client, method, url):
        assert getattr(api_client, method)(url).status_code == 401

    def test_list_only_shows_my_logs(self, client, user):
        mine = ReadingLogFactory(user=user)
        ReadingLogFactory()
        assert [r["id"] for r in client.get(LOGS).json()["results"]] == [mine.id]

    @pytest.mark.parametrize("method", ["get", "patch", "delete"])
    def test_other_users_log_is_404(self, client, method):
        theirs = ReadingLogFactory(pages_read=30)
        response = getattr(client, method)(detail(theirs), {"pages_read": 1}, format="json")
        assert response.status_code == 404
        theirs.refresh_from_db()
        assert theirs.pages_read == 30

    def test_cannot_log_a_book_only_on_someone_elses_shelf(self, client):
        theirs = UserBookFactory(status=S.READING)
        response = client.post(LOGS, {"book_id": theirs.book_id, "pages_read": 10}, format="json")
        assert response.status_code == 400
        assert response.json() == {"book_id": ["Add this book to your shelf first."]}


class TestCreate:
    def test_new_log_201_with_shelf_entry(self, client, reading):
        response = client.post(LOGS, {"book_id": reading.book_id, "pages_read": 25}, format="json")
        assert response.status_code == 201
        body = response.json()
        assert body["book_id"] == reading.book_id and body["pages_read"] == 25
        assert body["log_date"] == timezone.localdate().isoformat()
        assert body["shelf_entry"] == {
            "id": reading.id,
            "status": "reading",
            "started_at": "2026-11-01",
            "pages_logged": 25,
        }

    def test_same_day_adds_and_returns_200(self, client, reading):
        payload = {"book_id": reading.book_id, "pages_read": 25}
        first = client.post(LOGS, payload, format="json")
        second = client.post(LOGS, {**payload, "pages_read": 10}, format="json")
        assert (first.status_code, second.status_code) == (201, 200)
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["pages_read"] == 35
        assert second.json()["shelf_entry"]["pages_logged"] == 35

    def test_want_to_read_moves_to_reading(self, client, user):
        ub = UserBookFactory(user=user, status=S.WANT_TO_READ)
        day = yesterday()
        body = client.post(
            LOGS,
            {"book_id": ub.book_id, "pages_read": 5, "log_date": day.isoformat()},
            format="json",
        ).json()
        assert body["shelf_entry"]["status"] == "reading"
        assert body["shelf_entry"]["started_at"] == day.isoformat()

    def test_backfill_moves_started_at_in_response(self, client, reading):
        body = client.post(
            LOGS,
            {"book_id": reading.book_id, "pages_read": 5, "log_date": "2026-10-20"},
            format="json",
        ).json()
        assert body["shelf_entry"]["started_at"] == "2026-10-20"

    def test_cap_400(self, client, reading, settings):
        settings.MAX_PAGES_PER_DAY = 50
        response = client.post(LOGS, {"book_id": reading.book_id, "pages_read": 51}, format="json")
        assert response.status_code == 400 and "pages_read" in response.json()

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"pages_read": 10},
            {"book_id": 1},
            {"book_id": 1, "pages_read": 0},
            {"book_id": 1, "pages_read": -5},
            {"book_id": 1, "pages_read": 10, "log_date": "16/11/2026"},
            {"book_id": 1, "pages_read": 10, "user": 2},
        ],
        ids=["empty", "no-book", "no-pages", "zero", "negative", "bad-date", "unknown-field"],
    )
    def test_shape_errors_400(self, client, payload):
        assert client.post(LOGS, payload, format="json").status_code == 400
        assert not ReadingLog.objects.exists()

    def test_unknown_book_400(self, client):
        response = client.post(LOGS, {"book_id": 999999, "pages_read": 10}, format="json")
        assert response.json() == {"book_id": ["No catalog book with this ID."]}

    def test_book_in_catalog_but_not_on_shelf_400(self, client):
        book = BookFactory()
        response = client.post(LOGS, {"book_id": book.id, "pages_read": 10}, format="json")
        assert response.status_code == 400 and "book_id" in response.json()

    def test_future_date_400(self, client, reading):
        tomorrow = (timezone.localdate() + dt.timedelta(days=1)).isoformat()
        response = client.post(
            LOGS,
            {"book_id": reading.book_id, "pages_read": 10, "log_date": tomorrow},
            format="json",
        )
        assert response.status_code == 400 and "log_date" in response.json()


class TestList:
    def test_newest_day_first_and_shape(self, client, user):
        ReadingLogFactory(user=user, log_date=dt.date(2026, 11, 1))
        newest = ReadingLogFactory(user=user, log_date=dt.date(2026, 11, 10))
        rows = client.get(LOGS).json()["results"]
        assert rows[0]["id"] == newest.id
        assert set(rows[0]) == {
            "id",
            "book_id",
            "log_date",
            "pages_read",
            "created_at",
            "updated_at",
        }

    def test_filters(self, client, user):
        book = BookFactory()
        ReadingLogFactory(user=user, book=book, log_date=dt.date(2026, 10, 31))
        in_range = ReadingLogFactory(user=user, book=book, log_date=dt.date(2026, 11, 5))
        ReadingLogFactory(user=user, log_date=dt.date(2026, 11, 5))  # other book
        rows = client.get(LOGS, {"book": book.id, "from": "2026-11-01", "to": "2026-11-30"}).json()
        assert [r["id"] for r in rows["results"]] == [in_range.id]

    @pytest.mark.parametrize("params", [{"book": "x"}, {"from": "yesterday"}, {"to": "2026-13-01"}])
    def test_bad_filters_400(self, client, params):
        assert client.get(LOGS, params).status_code == 400

    def test_paginated(self, client, user):
        book = BookFactory()
        for day in range(1, 23):
            ReadingLogFactory(user=user, book=book, log_date=dt.date(2026, 10, day))
        body = client.get(LOGS).json()
        assert body["count"] == 22 and len(body["results"]) == 20


class TestUpdateAndDelete:
    def test_patch_sets_total(self, client, user, reading):
        log = ReadingLogFactory(
            user=user, book=reading.book, log_date=dt.date(2026, 11, 5), pages_read=40
        )
        body = client.patch(detail(log), {"pages_read": 12}, format="json").json()
        assert body["pages_read"] == 12 and body["shelf_entry"]["pages_logged"] == 12

    def test_patch_onto_taken_day_400_with_conflict_id(self, client, user, reading):
        log = ReadingLogFactory(user=user, book=reading.book, log_date=dt.date(2026, 11, 5))
        taken = ReadingLogFactory(user=user, book=reading.book, log_date=dt.date(2026, 11, 6))
        response = client.patch(detail(log), {"log_date": "2026-11-06"}, format="json")
        assert response.status_code == 400
        body = response.json()
        assert body["conflict_id"] == taken.id and "log_date" in body

    def test_patch_date_backfills_started_at(self, client, user, reading):
        log = ReadingLogFactory(user=user, book=reading.book, log_date=dt.date(2026, 11, 5))
        body = client.patch(detail(log), {"log_date": "2026-10-25"}, format="json").json()
        assert body["shelf_entry"]["started_at"] == "2026-10-25"

    @pytest.mark.parametrize(
        "payload", [{"pages_read": 0}, {"book_id": 2}, {"log_date": "nope"}, {"user": 1}]
    )
    def test_patch_shape_errors_400(self, client, user, reading, payload):
        log = ReadingLogFactory(user=user, book=reading.book)
        assert client.patch(detail(log), payload, format="json").status_code == 400

    def test_put_not_allowed(self, client, user):
        log = ReadingLogFactory(user=user)
        assert client.put(detail(log), {"pages_read": 3}, format="json").status_code == 405

    def test_retrieve(self, client, user):
        log = ReadingLogFactory(user=user, pages_read=17)
        assert client.get(detail(log)).json()["pages_read"] == 17

    def test_delete_keeps_shelf_entry_unchanged(self, client, user, reading):
        log = ReadingLogFactory(user=user, book=reading.book, log_date=dt.date(2026, 11, 5))
        assert client.delete(detail(log)).status_code == 204
        assert not ReadingLog.objects.filter(pk=log.pk).exists()
        reading.refresh_from_db()
        assert reading.status == S.READING and reading.started_at == dt.date(2026, 11, 1)

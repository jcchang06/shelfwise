"""Resolving and dismissing unmatched rows (I-4): service rules and the API."""

import datetime as dt

import pytest
import responses
from django.urls import reverse

from accounts.tests.factories import UserFactory
from catalog.models import Book
from catalog.services import google_books
from catalog.tests.factories import BookFactory
from imports.models import GoodreadsImport, GoodreadsLink, ImportRow
from imports.resolution import RowNotResolvableError, dismiss_row, resolve_row
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

from .helpers import make_import, make_row

pytestmark = pytest.mark.django_db

Status = GoodreadsImport.Status
State = ImportRow.State


def finished_import_with_unmatched(user=None, **row_fields):
    """A done import whose matched rows are gone: 3 created, 1 unmatched row left."""
    imp = make_import(user, status=Status.DONE, created_count=3, unmatched_count=1)
    row = make_row(
        imp,
        4,
        state=State.UNMATCHED,
        note="No book with this title and author found.",
        **row_fields,
    )
    imp.total_rows, imp.processed_rows = 4, 4
    imp.save()
    return imp, row


class TestResolveService:
    def test_done_import_adjusts_counters_and_deletes_the_row(self):
        imp, row = finished_import_with_unmatched(
            status="finished", rating=4, date_read=dt.date(2024, 5, 1)
        )
        book = BookFactory()

        result = resolve_row(imp, row.pk, book)

        assert result.state == State.CREATED and result.match_method == ImportRow.MatchMethod.MANUAL
        assert result.note == ""  # the old "why unmatched" note is gone
        imp.refresh_from_db()
        assert (imp.created_count, imp.unmatched_count) == (4, 0)
        assert not ImportRow.objects.filter(pk=row.pk).exists()  # deleted (privacy)
        entry = UserBook.objects.get(user=imp.user, book=book)
        assert (entry.status, entry.rating, entry.finished_at) == (
            "finished",
            4,
            dt.date(2024, 5, 1),
        )
        assert GoodreadsLink.objects.get().user_book == entry

    def test_running_import_keeps_the_row_and_recounts(self):
        imp = make_import(status=Status.PAUSED)
        make_row(imp, 1)  # still pending
        row = make_row(imp, 2, state=State.UNMATCHED)

        resolve_row(imp, row.pk, BookFactory())

        row.refresh_from_db()
        assert row.state == State.CREATED  # kept until the import finishes
        imp.refresh_from_db()
        assert (imp.created_count, imp.unmatched_count, imp.processed_rows) == (1, 0, 1)

    def test_resolving_onto_a_book_already_on_the_shelf_is_skipped(self):
        imp, row = finished_import_with_unmatched()
        entry = UserBookFactory(user=imp.user)
        result = resolve_row(imp, row.pk, entry.book)
        assert result.state == State.SKIPPED
        imp.refresh_from_db()
        assert (imp.skipped_count, imp.unmatched_count) == (1, 0)

    def test_a_rule_failure_keeps_the_row_as_failed(self):
        imp, row = finished_import_with_unmatched(status="finished", date_read=dt.date(2999, 1, 1))
        result = resolve_row(imp, row.pk, BookFactory())
        assert result.state == State.FAILED and "future" in result.note
        imp.refresh_from_db()
        assert (imp.failed_count, imp.unmatched_count) == (1, 0)
        assert ImportRow.objects.filter(pk=row.pk, state=State.FAILED).exists()

    def test_only_unmatched_rows_can_be_resolved(self):
        imp = make_import()
        row = make_row(imp, 1, state=State.FAILED)
        with pytest.raises(RowNotResolvableError):
            resolve_row(imp, row.pk, BookFactory())

    def test_a_row_from_another_import_is_not_found(self):
        _, row = finished_import_with_unmatched()
        with pytest.raises(ImportRow.DoesNotExist):
            resolve_row(make_import(), row.pk, BookFactory())


class TestDismissService:
    def test_done_import_counts_it_as_skipped_and_deletes_it(self):
        imp, row = finished_import_with_unmatched()
        result = dismiss_row(imp, row.pk)
        assert result.state == State.DISMISSED
        imp.refresh_from_db()
        assert (imp.skipped_count, imp.unmatched_count) == (1, 0)
        assert not ImportRow.objects.filter(pk=row.pk).exists()
        assert not UserBook.objects.exists()

    def test_cannot_dismiss_twice(self):
        imp = make_import(status=Status.PAUSED)
        row = make_row(imp, 1, state=State.UNMATCHED)
        dismiss_row(imp, row.pk)
        with pytest.raises(RowNotResolvableError):
            dismiss_row(imp, row.pk)


# --- API -------------------------------------------------------------------------------


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def rows_url(imp, state=None):
    url = reverse("imports:import-rows", args=[imp.pk])
    return f"{url}?state={state}" if state else url


class TestRowsApi:
    def test_lists_unmatched_rows_with_a_search_query(self, client, user):
        imp, row = finished_import_with_unmatched(
            user, title="The Glass Orchard", author="Mara Vell, Bram Sato"
        )
        make_row(imp, 5, state=State.FAILED, note="No title")
        body = client.get(rows_url(imp)).json()
        assert [r["id"] for r in body["results"]] == [row.id]
        assert body["results"][0]["search_query"] == "The Glass Orchard Mara Vell"
        assert body["results"][0]["note"] == "No book with this title and author found."

    def test_lists_failed_rows(self, client, user):
        imp, _ = finished_import_with_unmatched(user)
        failed = make_row(imp, 5, state=State.FAILED, note="No title")
        assert [r["id"] for r in client.get(rows_url(imp, "failed")).json()["results"]] == [
            failed.id
        ]

    def test_only_unmatched_or_failed_can_be_listed(self, client, user):
        imp, _ = finished_import_with_unmatched(user)
        assert client.get(rows_url(imp, "created")).status_code == 400

    def test_another_users_import_is_404(self, client):
        imp, row = finished_import_with_unmatched()
        assert client.get(rows_url(imp)).status_code == 404
        assert client.post(reverse("imports:row-dismiss", args=[imp.pk, row.pk])).status_code == 404


class TestResolveApi:
    def url(self, imp, row):
        return reverse("imports:row-resolve", args=[imp.pk, row.pk])

    def test_resolve_with_a_catalog_book(self, client, user):
        imp, row = finished_import_with_unmatched(user, status="finished", rating=5)
        book = BookFactory()
        response = client.post(self.url(imp, row), {"book_id": book.id}, format="json")
        assert response.status_code == 200
        body = response.json()
        assert body["row"]["state"] == "created" and body["book_id"] == book.id
        assert body["import"]["unmatched_count"] == 0 and body["import"]["created_count"] == 4
        assert UserBook.objects.get(user=user).rating == 5

    def test_resolve_from_a_search_result(self, client, user):
        imp, row = finished_import_with_unmatched(user)
        volume = {
            "id": "vol9",
            "volumeInfo": {"title": "The Glass Orchard", "authors": ["Mara Vell"]},
        }
        with responses.RequestsMock() as rsps:
            rsps.get(f"{google_books.API_ROOT}/volumes/vol9", json=volume)
            response = client.post(
                self.url(imp, row), {"source": "google_books", "source_id": "vol9"}, format="json"
            )
        assert response.status_code == 200
        assert Book.objects.get(google_books_id="vol9").title == "The Glass Orchard"

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"book_id": 1, "source": "google_books", "source_id": "x"},
            {"source": "google_books", "source_id": "../evil"},
            {"book_id": 999999},
            {"book_id": 1, "status": "finished"},
        ],
        ids=["nothing", "both", "bad-source-id", "unknown-book", "unknown-field"],
    )
    def test_bad_payloads_400(self, client, user, payload):
        imp, row = finished_import_with_unmatched(user)
        BookFactory(id=1)
        assert client.post(self.url(imp, row), payload, format="json").status_code == 400
        row.refresh_from_db()
        assert row.state == State.UNMATCHED

    def test_already_handled_row_is_409(self, client, user):
        imp = make_import(user)
        row = make_row(imp, 1, state=State.FAILED)
        response = client.post(self.url(imp, row), {"book_id": BookFactory().id}, format="json")
        assert response.status_code == 409

    def test_unknown_volume_404_and_source_down_503(self, client, user):
        imp, row = finished_import_with_unmatched(user)
        with responses.RequestsMock() as rsps:
            rsps.get(f"{google_books.API_ROOT}/volumes/missing", status=404, json={})
            rsps.get(f"{google_books.API_ROOT}/volumes/down", status=500)
            missing = client.post(
                self.url(imp, row),
                {"source": "google_books", "source_id": "missing"},
                format="json",
            )
            down = client.post(
                self.url(imp, row), {"source": "google_books", "source_id": "down"}, format="json"
            )
        assert (missing.status_code, down.status_code) == (404, 503)


class TestDismissApi:
    def test_dismiss(self, client, user):
        imp, row = finished_import_with_unmatched(user)
        response = client.post(reverse("imports:row-dismiss", args=[imp.pk, row.pk]))
        assert response.status_code == 200
        assert response.json()["row"]["state"] == "dismissed"
        assert response.json()["import"]["skipped_count"] == 1

    def test_dismissing_a_handled_row_is_409(self, client, user):
        imp = make_import(user, status=Status.PAUSED)
        row = make_row(imp, 1, state=State.CREATED)
        assert client.post(reverse("imports:row-dismiss", args=[imp.pk, row.pk])).status_code == 409

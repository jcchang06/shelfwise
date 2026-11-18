"""Shelf endpoints (T-2, T-4, T-6). Rule details are covered in test_shelf_services.py;
these tests check the HTTP contract, user isolation and that the rules are wired in."""

import datetime as dt

import pytest
import responses
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from accounts.tests.factories import UserFactory
from catalog.models import Book
from catalog.services import google_books
from catalog.tests.factories import AuthorFactory, BookFactory
from tracking.models import ReadingLog, UserBook

from .factories import ReadingLogFactory, UserBookFactory

pytestmark = pytest.mark.django_db

S = UserBook.Status
SHELF = reverse("tracking:shelf-list")


def detail(user_book) -> str:
    return reverse("tracking:shelf-detail", args=[user_book.pk])


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def no_network():
    """Fails any test that tries to reach a book API."""
    with responses.RequestsMock() as rsps:
        yield rsps


class TestAuthAndIsolation:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("get", SHELF),
            ("post", SHELF),
            ("get", "/api/shelf/1/"),
            ("patch", "/api/shelf/1/"),
            ("delete", "/api/shelf/1/"),
        ],
    )
    def test_anonymous_gets_401(self, api_client, method, url):
        assert getattr(api_client, method)(url).status_code == 401

    def test_list_only_shows_my_books(self, client, user):
        mine = UserBookFactory(user=user)
        UserBookFactory()  # someone else's
        ids = [row["id"] for row in client.get(SHELF).json()["results"]]
        assert ids == [mine.id]

    @pytest.mark.parametrize("method", ["get", "patch", "delete"])
    def test_other_users_entry_is_404(self, client, method):
        theirs = UserBookFactory(status=S.READING)
        response = getattr(client, method)(detail(theirs), {"status": "finished"}, format="json")
        assert response.status_code == 404
        theirs.refresh_from_db()
        assert theirs.status == S.READING  # untouched

    def test_cannot_delete_other_users_logs(self, client, user):
        book = BookFactory()
        mine = UserBookFactory(user=user, book=book)
        ReadingLogFactory(user=user, book=book)
        ReadingLogFactory(book=book)  # another user's log for the same book
        client.delete(detail(mine))
        assert ReadingLog.objects.filter(book=book).count() == 1


class TestList:
    def test_entry_shape(self, client, user):
        clarke = AuthorFactory(name="Susanna Clarke")
        book = BookFactory(title="Piranesi", page_count=272, authors=[clarke])
        UserBookFactory(user=user, book=book, status=S.READING)
        ReadingLogFactory(user=user, book=book, pages_read=30, log_date=dt.date(2026, 11, 1))
        ReadingLogFactory(user=user, book=book, pages_read=25, log_date=dt.date(2026, 11, 2))

        row = client.get(SHELF).json()["results"][0]

        assert row["book"] == {
            "id": book.id,
            "title": "Piranesi",
            "authors": ["Susanna Clarke"],
            "author_links": [{"id": clarke.id, "name": "Susanna Clarke"}],
            "cover_url": book.cover_url,
            "page_count": 272,
        }
        assert row["pages_logged"] == 55 and row["reading_log_count"] == 2
        assert row["status"] == "reading"

    def test_zero_logs(self, client, user):
        UserBookFactory(user=user)
        row = client.get(SHELF).json()["results"][0]
        assert (row["pages_logged"], row["reading_log_count"]) == (0, 0)

    def test_filter_by_status(self, client, user):
        reading = UserBookFactory(user=user, status=S.READING)
        UserBookFactory(user=user, status=S.WANT_TO_READ)
        ids = [r["id"] for r in client.get(SHELF, {"status": "reading"}).json()["results"]]
        assert ids == [reading.id]

    def test_filter_by_book(self, client, user):
        target = UserBookFactory(user=user)
        UserBookFactory(user=user)
        ids = [r["id"] for r in client.get(SHELF, {"book": target.book_id}).json()["results"]]
        assert ids == [target.id]

    def test_ordering_by_title(self, client, user):
        for title in ["Circe", "Atonement", "Beloved"]:
            UserBookFactory(user=user, book=BookFactory(title=title))
        titles = [
            r["book"]["title"] for r in client.get(SHELF, {"ordering": "title"}).json()["results"]
        ]
        assert titles == ["Atonement", "Beloved", "Circe"]

    @pytest.mark.parametrize(
        "params", [{"status": "abandoned"}, {"book": "abc"}, {"ordering": "stars"}]
    )
    def test_bad_query_params_400(self, client, params):
        assert client.get(SHELF, params).status_code == 400

    def test_paginated(self, client, user):
        for _ in range(21):
            UserBookFactory(user=user)
        body = client.get(SHELF).json()
        assert body["count"] == 21 and len(body["results"]) == 20 and body["next"]

    def test_query_count_does_not_grow_with_rows(self, client, user, django_assert_max_num_queries):
        for _ in range(10):
            ub = UserBookFactory(
                user=user, book=BookFactory(authors=[AuthorFactory(), AuthorFactory()])
            )
            ReadingLogFactory(user=user, book=ub.book)
        # auth is forced, so: count + page + author prefetch
        with django_assert_max_num_queries(3):
            client.get(SHELF)


class TestFiltersAndSorts:
    """Author and rating filters, author and rating sorts (T-2)."""

    def shelve(self, user, title, author_names=(), rating=None, status=S.FINISHED):
        authors = [AuthorFactory(name=name) for name in author_names]
        book = BookFactory(title=title, authors=authors)
        return UserBookFactory(user=user, book=book, status=status, rating=rating)

    def titles(self, client, **params):
        return [r["book"]["title"] for r in client.get(SHELF, params).json()["results"]]

    def test_author_filter_includes_co_authored_books_and_names_the_author(self, client, user):
        mara = AuthorFactory(name="Mara Vell")
        UserBookFactory(user=user, book=BookFactory(title="Solo", authors=[mara]))
        UserBookFactory(user=user, book=BookFactory(title="Duet", authors=[AuthorFactory(), mara]))
        UserBookFactory(user=user, book=BookFactory(title="Other"))
        UserBookFactory(book=BookFactory(title="Not mine", authors=[mara]))  # another user

        body = client.get(SHELF, {"author": mara.pk, "ordering": "title"}).json()
        assert [r["book"]["title"] for r in body["results"]] == ["Duet", "Solo"]
        assert body["filters"] == {"author": {"id": mara.pk, "name": "Mara Vell"}}

    def test_filters_are_null_without_an_author_and_unknown_authors_are_empty(self, client, user):
        self.shelve(user, "Any")
        assert client.get(SHELF).json()["filters"] == {"author": None}
        body = client.get(SHELF, {"author": 999999}).json()
        assert body["results"] == [] and body["filters"] == {"author": None}

    def test_rating_minimum_and_unrated(self, client, user):
        for title, rating in [("Five", 5), ("Four", 4), ("Three", 3), ("None", None)]:
            self.shelve(user, title, rating=rating)
        assert self.titles(client, rating="4", ordering="title") == ["Five", "Four"]
        assert self.titles(client, rating="unrated") == ["None"]

    def test_filters_combine_with_status(self, client, user):
        mara = AuthorFactory(name="Mara Vell")
        UserBookFactory(
            user=user, book=BookFactory(title="A", authors=[mara]), status=S.FINISHED, rating=5
        )
        UserBookFactory(user=user, book=BookFactory(title="B", authors=[mara]), status=S.READING)
        UserBookFactory(user=user, book=BookFactory(title="C"), status=S.FINISHED, rating=5)
        assert self.titles(client, status="finished", author=mara.pk, rating="4") == ["A"]

    def test_sort_by_last_name_with_particles_and_suffixes(self, client, user):
        for title, name in [
            ("Plain", "Andy Weir"),
            ("Suffix", "Martin Luther King Jr."),
            ("Particle Le", "Ursula K. Le Guin"),
            ("Particle du", "Daphne du Maurier"),
            ("Particle van", "Ludwig  VAN Beethoven"),
            ("Roman numeral", "John Smith III"),
        ]:
            self.shelve(user, title, [name])
        self.shelve(user, "No author")
        assert self.titles(client, ordering="author") == [
            "Particle du",  # du maurier
            "Suffix",  # king
            "Particle Le",  # le guin
            "Roman numeral",  # smith
            "Particle van",  # van beethoven
            "Plain",  # weir
            "No author",  # no key: last
        ]

    def test_author_sort_uses_the_first_author_then_title(self, client, user):
        self.shelve(user, "Zebra", ["Andy Weir"])
        self.shelve(user, "apple", ["Andy Weir", "Mara Vell"])
        self.shelve(user, "Middle", ["Mara Vell", "Andy Weir"])
        assert self.titles(client, ordering="author") == ["Middle", "apple", "Zebra"]

    def test_sort_by_rating_highest_first_unrated_last_ties_by_title(self, client, user):
        for title, rating in [("b", 4), ("A", 4), ("Top", 5), ("Unrated", None), ("Low", 1)]:
            self.shelve(user, title, rating=rating)
        assert self.titles(client, ordering="-rating") == ["Top", "A", "b", "Low", "Unrated"]

    @pytest.mark.parametrize(
        "params", [{"author": "abc"}, {"rating": "6"}, {"rating": "0"}, {"rating": "any"}]
    )
    def test_bad_filter_values_400(self, client, params):
        assert client.get(SHELF, params).status_code == 400

    def test_query_count_is_fixed_with_every_filter_and_sort(
        self, client, user, django_assert_max_num_queries
    ):
        mara = AuthorFactory(name="Mara Vell")
        for n in range(10):
            ub = UserBookFactory(
                user=user,
                status=S.FINISHED,
                rating=5,
                book=BookFactory(title=f"Book {n}", authors=[mara, AuthorFactory()]),
            )
            ReadingLogFactory(user=user, book=ub.book)
        # count + page + author prefetch + the filter author's name
        for ordering in ("author", "-rating"):
            with django_assert_max_num_queries(4):
                response = client.get(
                    SHELF,
                    {"status": "finished", "author": mara.pk, "rating": "4", "ordering": ordering},
                )
            assert response.json()["count"] == 10


class TestAdd:
    def test_adding_another_copy_of_a_shelved_book_is_a_409(self, client, user, no_network):
        imported = BookFactory(
            title="A Court of Frost and Starlight",
            open_library_key="OL22W",
            authors=[AuthorFactory(name="Sarah J. Maas")],
        )
        entry = UserBookFactory(user=user, book=imported)
        google_copy = BookFactory(
            title="A Court of Frost and Starlight (A Court of Thorns and Roses)",
            authors=[AuthorFactory(name="Sarah J Maas")],
        )
        response = client.post(SHELF, {"book_id": google_copy.id}, format="json")
        assert response.status_code == 409
        assert response.json() == {"detail": "This book is already on your shelf.", "id": entry.id}
        assert UserBook.objects.filter(user=user).count() == 1

    def test_same_title_by_another_author_is_a_different_book(self, client, user, no_network):
        UserBookFactory(
            user=user,
            book=BookFactory(title="Persuasion", authors=[AuthorFactory(name="Jane Austen")]),
        )
        other = BookFactory(title="Persuasion", authors=[AuthorFactory(name="Someone Else")])
        assert client.post(SHELF, {"book_id": other.id}, format="json").status_code == 201

    def test_add_by_book_id_defaults_to_want_to_read(self, client, user, no_network):
        book = BookFactory()
        response = client.post(SHELF, {"book_id": book.id}, format="json")
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "want_to_read" and body["book"]["id"] == book.id
        assert UserBook.objects.get(user=user).book == book

    def test_add_as_finished_with_rating(self, client, user):
        book = BookFactory()
        response = client.post(
            SHELF, {"book_id": book.id, "status": "finished", "rating": 4}, format="json"
        )
        assert response.status_code == 201
        body = response.json()
        assert body["rating"] == 4 and body["finished_at"] == timezone.localdate().isoformat()

    def test_add_by_source_saves_to_catalog_first(self, client, user):
        volume = {
            "id": "vol1",
            "volumeInfo": {"title": "Project Hail Mary", "authors": ["Andy Weir"]},
        }
        with responses.RequestsMock() as rsps:
            rsps.get(f"{google_books.API_ROOT}/volumes/vol1", json=volume)
            response = client.post(
                SHELF,
                {"source": "google_books", "source_id": "vol1", "status": "reading"},
                format="json",
            )
        assert response.status_code == 201
        assert Book.objects.get(google_books_id="vol1").title == "Project Hail Mary"
        assert response.json()["status"] == "reading"

    def test_add_by_source_for_book_already_in_catalog_makes_no_call(self, client, no_network):
        BookFactory(google_books_id="vol1")
        response = client.post(
            SHELF, {"source": "google_books", "source_id": "vol1"}, format="json"
        )
        assert response.status_code == 201

    def test_duplicate_is_409_with_existing_id(self, client, user):
        existing = UserBookFactory(user=user)
        response = client.post(
            SHELF, {"book_id": existing.book_id, "status": "reading"}, format="json"
        )
        assert response.status_code == 409
        assert response.json()["id"] == existing.id
        existing.refresh_from_db()
        assert existing.status == S.WANT_TO_READ  # the sent status wasn't applied

    def test_same_book_on_another_users_shelf_is_fine(self, client):
        theirs = UserBookFactory()
        assert client.post(SHELF, {"book_id": theirs.book_id}, format="json").status_code == 201

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"book_id": 1, "source": "google_books", "source_id": "vol1"},
            {"source": "google_books"},
            {"source": "google_books", "source_id": "../evil"},
            {"book_id": 999999},
        ],
        ids=["nothing", "both", "source-without-id", "bad-source-id", "unknown-book-id"],
    )
    def test_bad_book_reference_400(self, client, no_network, payload):
        assert client.post(SHELF, payload, format="json").status_code == 400
        assert not UserBook.objects.exists()

    def test_rules_apply_on_add(self, client):
        book = BookFactory()
        response = client.post(SHELF, {"book_id": book.id, "rating": 5}, format="json")
        assert response.status_code == 400 and "rating" in response.json()

    def test_unknown_field_rejected(self, client):
        book = BookFactory()
        response = client.post(SHELF, {"book_id": book.id, "user": 1}, format="json")
        assert response.status_code == 400 and "user" in response.json()

    def test_unknown_source_volume_404(self, client):
        with responses.RequestsMock() as rsps:
            rsps.get(f"{google_books.API_ROOT}/volumes/missing", status=404, json={})
            response = client.post(
                SHELF, {"source": "google_books", "source_id": "missing"}, format="json"
            )
        assert response.status_code == 404

    def test_source_unavailable_503(self, client, no_network):
        cache.set(google_books.QUOTA_FLAG_KEY, True)
        response = client.post(
            SHELF, {"source": "google_books", "source_id": "vol1"}, format="json"
        )
        assert response.status_code == 503


class TestUpdate:
    def test_mark_finished_and_rate(self, client, user):
        ub = UserBookFactory(user=user, status=S.READING, started_at=dt.date(2026, 11, 1))
        response = client.patch(
            detail(ub), {"status": "finished", "rating": 5, "review": "Wow"}, format="json"
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["status"], body["rating"], body["review"]) == ("finished", 5, "Wow")
        assert body["finished_at"] == timezone.localdate().isoformat()

    def test_mark_dnf_uses_logged_pages(self, client, user):
        ub = UserBookFactory(user=user, status=S.READING)
        ReadingLogFactory(user=user, book=ub.book, pages_read=64)
        body = client.patch(
            detail(ub), {"status": "dnf", "dnf_reason": "pacing"}, format="json"
        ).json()
        assert (body["status"], body["dnf_page"], body["dnf_reason"]) == ("dnf", 64, "pacing")
        assert body["pages_logged"] == 64 and body["reading_log_count"] == 1  # logs kept

    def test_rule_errors_are_400_by_field(self, client, user):
        ub = UserBookFactory(user=user, status=S.READING)
        response = client.patch(detail(ub), {"rating": 4}, format="json")
        assert response.status_code == 400
        assert response.json() == {"rating": ["You can rate a book only when it's finished."]}

    def test_dnf_without_a_reason_is_not_specified(self, client, user):
        ub = UserBookFactory(user=user, status=S.READING)
        response = client.patch(detail(ub), {"status": "dnf"}, format="json")
        assert response.status_code == 200
        assert response.json()["dnf_reason"] == "not_specified"

    @pytest.mark.parametrize(
        "payload",
        [
            {"rating": 6},
            {"rating": 0},
            {"status": "abandoned"},
            {"dnf_reason": "boring"},
            {"dnf_page": -1},
            {"started_at": "not-a-date"},
        ],
    )
    def test_type_errors_400(self, client, user, payload):
        ub = UserBookFactory(user=user, status=S.DNF, dnf_reason="pacing")
        assert client.patch(detail(ub), payload, format="json").status_code == 400

    @pytest.mark.parametrize("field", ["book", "book_id", "user", "pages_logged", "id"])
    def test_cannot_change_read_only_fields(self, client, user, field):
        ub = UserBookFactory(user=user)
        response = client.patch(detail(ub), {field: 1}, format="json")
        assert response.status_code == 400 and field in response.json()

    def test_put_not_allowed(self, client, user):
        ub = UserBookFactory(user=user)
        assert client.put(detail(ub), {"status": "reading"}, format="json").status_code == 405

    def test_reread_keeps_rating(self, client, user):
        ub = UserBookFactory(user=user, finished=True, rating=5)
        body = client.patch(detail(ub), {"status": "reading"}, format="json").json()
        assert body["rating"] == 5 and body["finished_at"] is not None
        assert body["started_at"] == timezone.localdate().isoformat()


class TestRetrieveAndDelete:
    def test_retrieve(self, client, user):
        ub = UserBookFactory(user=user, dnf=True)
        body = client.get(detail(ub)).json()
        assert body["id"] == ub.id and body["dnf_reason"] == "pacing"

    def test_delete_removes_entry_and_my_logs_for_that_book(self, client, user):
        ub = UserBookFactory(user=user)
        ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2026, 11, 1))
        ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2026, 11, 2))
        other_book_log = ReadingLogFactory(user=user)

        assert client.delete(detail(ub)).status_code == 204

        assert not UserBook.objects.filter(pk=ub.pk).exists()
        assert list(ReadingLog.objects.filter(user=user)) == [other_book_log]
        assert Book.objects.filter(pk=ub.book_id).exists()  # the catalog book stays


def test_pages_logged_counts_current_read_but_log_count_counts_all(client, user):
    # SQL version of services.current_read_logs (views.shelf_for) must agree with it.
    ub = UserBookFactory(
        user=user,
        status=S.READING,
        started_at=dt.date(2026, 11, 1),
        finished_at=dt.date(2025, 3, 9),  # a re-read: first read ended in 2025
    )
    ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2025, 3, 1), pages_read=300)
    ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2026, 11, 1), pages_read=20)
    ReadingLogFactory(user=user, book=ub.book, log_date=dt.date(2026, 11, 2), pages_read=15)

    row = client.get(detail(ub)).json()

    assert row["pages_logged"] == 35
    assert row["reading_log_count"] == 3  # removing the book deletes all three

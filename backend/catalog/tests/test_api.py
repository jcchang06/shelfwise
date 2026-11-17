"""HTTP endpoints for search (C-1), save (C-2) and book detail. All external calls mocked."""

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle

from accounts.tests.factories import UserFactory
from catalog.models import Book
from catalog.services import google_books
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

from .conftest import GOOGLE_SEARCH_RE, OL_SEARCH_RE, google_volume_url, load_fixture
from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db

SEARCH = reverse("catalog:book-search")
BOOKS = reverse("catalog:book-list")


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def full_google_page():
    item = load_fixture("google_search")["items"][0]
    items = [{**item, "id": f"vol{i}"} for i in range(google_books.PAGE_SIZE)]
    return {"totalItems": 100, "items": items}


class TestAuthRequired:
    @pytest.mark.parametrize(
        ("method", "url"),
        [("get", SEARCH + "?q=dune"), ("post", BOOKS), ("get", "/api/books/1/")],
    )
    def test_anonymous_gets_401(self, api_client, method, url):
        assert getattr(api_client, method)(url).status_code == 401


class TestSearch:
    def test_returns_google_results(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        response = client.get(SEARCH, {"q": "project hail mary"})

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "google_books" and body["page"] == 1
        first = body["results"][0]
        assert set(first) == {
            "source",
            "source_id",
            "title",
            "authors",
            "description",
            "genres",
            "page_count",
            "published_date",
            "isbn_13",
            "cover_url",
            "book_id",
            "shelf",
            "author_links",
        }
        assert first["author_links"] == [{"id": None, "name": a} for a in first["authors"]]
        assert isinstance(first["authors"], list) and all(
            isinstance(a, str) for a in first["authors"]
        )
        assert first["book_id"] is None

    def test_marks_books_already_in_catalog(self, client, mocked):
        body = load_fixture("google_search")
        existing = BookFactory(google_books_id=body["items"][0]["id"])
        mocked.get(GOOGLE_SEARCH_RE, json=body)
        results = client.get(SEARCH, {"q": "project hail mary"}).json()["results"]
        assert results[0]["book_id"] == existing.id

    def test_falls_back_to_open_library(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, status=500)
        mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
        body = client.get(SEARCH, {"q": "project hail mary"}).json()
        assert body["source"] == "open_library" and body["results"]

    def test_next_page_only_when_page_is_full(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=full_google_page())
        assert client.get(SEARCH, {"q": "dune"}).json()["next_page"] == 2

        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        assert client.get(SEARCH, {"q": "other", "page": 3}).json()["next_page"] is None

    def test_empty_results(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
        mocked.get(OL_SEARCH_RE, json={"docs": []})
        body = client.get(SEARCH, {"q": "qzxqv"}).json()
        assert body["results"] == [] and body["next_page"] is None

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"q": ""},
            {"q": " a "},
            {"q": "x" * 201},
            {"q": "dune", "page": 0},
            {"q": "dune", "page": 11},
        ],
        ids=["missing", "empty", "one-char", "too-long", "page-0", "page-11"],
    )
    def test_invalid_params_400_without_calling_apis(self, client, mocked, params):
        assert client.get(SEARCH, params).status_code == 400
        assert len(mocked.calls) == 0

    def test_both_sources_down_gives_503(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, status=500)
        mocked.get(OL_SEARCH_RE, status=500)
        response = client.get(SEARCH, {"q": "dune"})
        assert response.status_code == 503
        assert "try again" in response.json()["detail"]

    def test_throttled_per_user(self, client, mocked, monkeypatch):
        monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"book_search": "2/minute"})
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        statuses = [client.get(SEARCH, {"q": f"dune {i}"}).status_code for i in range(3)]
        assert statuses == [200, 200, 429]

        # A different user has their own allowance.
        client.force_authenticate(UserFactory())
        assert client.get(SEARCH, {"q": "dune"}).status_code == 200


class TestSave:
    def test_creates_book_201(self, client, mocked):
        body = load_fixture("google_volume")
        mocked.get(google_volume_url(body["id"]), json=body)

        response = client.post(BOOKS, {"source": "google_books", "source_id": body["id"]})

        assert response.status_code == 201
        data = response.json()
        assert data["google_books_id"] == body["id"]
        assert data["title"] and data["authors"][0]["name"]
        assert Book.objects.filter(pk=data["id"]).exists()

    def test_existing_book_200_without_api_call(self, client, mocked):
        book = BookFactory(google_books_id="vol1")
        response = client.post(BOOKS, {"source": "google_books", "source_id": "vol1"})
        assert response.status_code == 200 and response.json()["id"] == book.id
        assert len(mocked.calls) == 0

    def test_saving_twice_is_idempotent(self, client, mocked):
        body = load_fixture("google_volume")
        mocked.get(google_volume_url(body["id"]), json=body)
        payload = {"source": "google_books", "source_id": body["id"]}
        first = client.post(BOOKS, payload)
        second = client.post(BOOKS, payload)
        assert (first.status_code, second.status_code) == (201, 200)
        assert first.json()["id"] == second.json()["id"]
        assert Book.objects.count() == 1

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"source": "goodreads", "source_id": "1"},
            {"source": "google_books", "source_id": "../../evil"},
            {"source": "google_books", "source_id": "abc?key=x"},
            {"source": "open_library", "source_id": "OL1A"},  # an author key, not a work
            {"source": "open_library", "source_id": "/works/OL1W"},
        ],
        ids=["missing", "bad-source", "path-traversal", "query-injection", "author-key", "path"],
    )
    def test_invalid_payload_400_without_calling_apis(self, client, mocked, payload):
        assert client.post(BOOKS, payload).status_code == 400
        assert len(mocked.calls) == 0

    def test_unknown_volume_404(self, client, mocked):
        mocked.get(google_volume_url("missing"), status=404, json={})
        response = client.post(BOOKS, {"source": "google_books", "source_id": "missing"})
        assert response.status_code == 404

    def test_quota_exhausted_503(self, client, mocked):
        cache.set(google_books.QUOTA_FLAG_KEY, True)
        response = client.post(BOOKS, {"source": "google_books", "source_id": "vol1"})
        assert response.status_code == 503
        assert len(mocked.calls) == 0


class TestDetail:
    def test_returns_book_with_ordered_authors(self, client):
        first, second = AuthorFactory(name="Terry Pratchett"), AuthorFactory(name="Neil Gaiman")
        book = BookFactory(title="Good Omens", authors=[first, second], series_number="2.5")

        data = client.get(reverse("catalog:book-detail", args=[book.pk])).json()

        assert data["title"] == "Good Omens"
        assert [a["name"] for a in data["authors"]] == ["Terry Pratchett", "Neil Gaiman"]
        assert data["published_date"] == book.published_date_display
        assert data["series_number"] == "2.5"

    def test_missing_book_404(self, client):
        assert client.get(reverse("catalog:book-detail", args=[999999])).status_code == 404

    def test_query_count_is_constant(self, client, django_assert_max_num_queries):
        book = BookFactory(authors=[AuthorFactory() for _ in range(5)])
        url = reverse("catalog:book-detail", args=[book.pk])
        with django_assert_max_num_queries(3):  # book + book_authors(+author join)
            client.get(url)


class TestSearchShelfStatus:
    """`shelf` (and `book_id`) are per-request data layered on top of cached source results."""

    def search(self, client, q="project hail mary"):
        return client.get(SEARCH, {"q": q}).json()["results"]

    def test_null_when_not_on_my_shelf(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        assert all(r["shelf"] is None for r in self.search(client))

    def test_shows_my_entry(self, client, user, mocked):
        body = load_fixture("google_search")
        book = BookFactory(google_books_id=body["items"][0]["id"])
        entry = UserBookFactory(user=user, book=book, status=UserBook.Status.READING)
        mocked.get(GOOGLE_SEARCH_RE, json=body)

        first = self.search(client)[0]

        assert first["book_id"] == book.id
        assert first["shelf"] == {"id": entry.id, "status": "reading"}

    def test_other_users_shelf_is_never_shown(self, client, mocked):
        body = load_fixture("google_search")
        book = BookFactory(google_books_id=body["items"][0]["id"])
        UserBookFactory(book=book)  # someone else's shelf
        mocked.get(GOOGLE_SEARCH_RE, json=body)

        first = self.search(client)[0]

        assert first["book_id"] == book.id  # the catalog is shared...
        assert first["shelf"] is None  # ...shelves are not

    def test_add_then_search_again_shows_book_id_and_shelf_despite_cache(self, client, mocked):
        """Search, add the book, search the same query again: the second response comes from
        the 24h source cache (no second Google call) yet shows the new book_id and shelf."""
        body = load_fixture("google_search")
        volume_id = body["items"][0]["id"]
        search_mock = mocked.get(GOOGLE_SEARCH_RE, json=body)
        mocked.get(google_volume_url(volume_id), json=load_fixture("google_volume"))

        before = self.search(client)[0]
        assert before["source_id"] == volume_id
        assert (before["book_id"], before["shelf"]) == (None, None)

        added = client.post(
            "/api/shelf/", {"source": "google_books", "source_id": volume_id}, format="json"
        )
        assert added.status_code == 201

        after = self.search(client)[0]

        assert search_mock.call_count == 1  # second search was served from the cache
        assert after["book_id"] == added.json()["book"]["id"]
        assert after["shelf"] == {"id": added.json()["id"], "status": "want_to_read"}

    def test_cache_holds_only_source_data(self, client, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        self.search(client)
        cached = google_books.search("project hail mary")  # served from the cache
        assert cached and all(not hasattr(r, "shelf") and not hasattr(r, "book_id") for r in cached)

    def test_shelf_lookup_is_one_query(self, client, user, mocked, django_assert_max_num_queries):

        body = full_google_page()
        for item in body["items"][:10]:
            UserBookFactory(user=user, book=BookFactory(google_books_id=item["id"], isbn_13=""))
        mocked.get(GOOGLE_SEARCH_RE, json=body)
        # catalog ids (google ids, OL keys, ISBNs) + shelf entries; auth is forced
        with django_assert_max_num_queries(4):
            results = self.search(client, "dune")
        assert sum(1 for r in results if r["shelf"]) == 10

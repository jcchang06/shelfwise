"""Author pages (C-5): the Open Library author client, key resolution, merging works with
the catalog, grouping by series, author IDs for links, and GET /api/authors/{id}/."""

from decimal import Decimal

import pytest
from django.urls import reverse
from responses import matchers

from accounts.tests.factories import UserFactory
from catalog.models import Author
from catalog.services import authors, open_library
from catalog.services.types import (
    AuthorCandidate,
    AuthorRef,
    AuthorWork,
    BookResult,
    BookSourceError,
    Source,
)
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

from .conftest import OL_SEARCH
from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db
OL_AUTHOR_SEARCH = f"{open_library.API_ROOT}/search/authors.json"


def doc(key, title, year=None, editions=1, language=None, cover=None):
    d = {"key": f"/works/{key}", "title": title, "edition_count": editions}
    if year:
        d["first_publish_year"] = year
    if language:
        d["language"] = language
    if cover:
        d["cover_i"] = cover
    return d


# --- Client -------------------------------------------------------------------------


class TestParseAuthorWorks:
    def test_keeps_english_or_unlabelled_works_one_per_title_oldest_first(self):
        works = open_library.parse_author_works(
            [
                doc("OL3W", "The Glass Orchard", 2019, editions=12, language=["eng"]),
                doc("OL4W", "The Glass Orchard", 2026, editions=1),  # a re-release
                doc("OL5W", "El huerto de cristal", 2020, language=["spa"]),
                doc("OL6W", "Winter Ledger", None, editions=2),
                doc("OL7W", "Salt Roads", 2015, language=["eng", "fre"], cover=42),
                {"key": "/works/OL8W"},  # no title
            ],
            "en",
        )
        assert [(w.work_key, w.first_publish_year) for w in works] == [
            ("OL7W", 2015),
            ("OL3W", 2019),
            ("OL6W", None),  # unknown year last
        ]
        assert works[0].cover_url.endswith("/42-L.jpg")

    def test_unknown_language_setting_keeps_everything(self):
        works = open_library.parse_author_works([doc("OL5W", "Huerto", language=["spa"])], "xx")
        assert len(works) == 1


class TestAuthorClient:
    def test_author_works_request_and_cache(self, mocked):
        mocked.get(
            OL_SEARCH,
            json={"docs": [doc("OL3W", "The Glass Orchard", 2019)]},
            match=[
                matchers.query_param_matcher(open_library.author_works_params("OL9A", "editions"))
            ],
        )
        first = open_library.author_works("OL9A", sort="editions")
        again = open_library.author_works("OL9A", sort="editions")
        assert first == again == [AuthorWork("OL3W", "The Glass Orchard", 2019, "", 1)]
        assert len(mocked.calls) == 1

    def test_search_authors_parses_and_caches(self, mocked):
        mocked.get(
            OL_AUTHOR_SEARCH,
            json={
                "docs": [
                    {
                        "key": "OL9A",
                        "name": "Mara Vell",
                        "alternate_names": ["M. Vell"],
                        "work_count": 7,
                    },
                    {"key": "OL10A"},  # no name
                ]
            },
        )
        found = open_library.search_authors("Mara Vell")
        open_library.search_authors("mara vell")  # same cache entry
        assert found == [AuthorCandidate("OL9A", "Mara Vell", ("M. Vell",), 7)]
        assert len(mocked.calls) == 1


# --- Key resolution -------------------------------------------------------------------


@pytest.fixture
def ol(monkeypatch):
    """Stub the Open Library client functions; record calls."""
    state = {"works": {}, "author_works": {}, "candidates": [], "calls": [], "fail": False}

    def maybe_fail():
        if state["fail"]:
            raise BookSourceError("down")

    def get_work(key):
        state["calls"].append(("work", key))
        maybe_fail()
        return state["works"][key]

    def author_works(key, sort="new"):
        state["calls"].append(("author_works", key, sort))
        maybe_fail()
        return state["author_works"].get((key, sort), state["author_works"].get(key, []))

    def search_authors(name):
        state["calls"].append(("search_authors", name))
        maybe_fail()
        return state["candidates"]

    monkeypatch.setattr(open_library, "get_work", get_work)
    monkeypatch.setattr(open_library, "author_works", author_works)
    monkeypatch.setattr(open_library, "search_authors", search_authors)
    return state


def result(key, *refs):
    return BookResult(Source.OPEN_LIBRARY, key, "Any", authors=tuple(refs))


class TestResolveAuthorKey:
    def test_uses_the_saved_key_without_requests(self, ol):
        author = AuthorFactory(open_library_key="OL9A")
        assert authors.resolve_author_key(author) == "OL9A"
        assert ol["calls"] == []

    def test_finds_the_key_in_a_catalog_books_work_and_saves_it(self, ol):
        author = AuthorFactory(name="Mara Vell")
        BookFactory(open_library_key="OL3W", authors=[author])
        ol["works"]["OL3W"] = result("OL3W", AuthorRef("Mara  Vell", "OL9A"))
        assert authors.resolve_author_key(author) == "OL9A"
        assert Author.objects.get(pk=author.pk).open_library_key == "OL9A"
        assert ("search_authors", "Mara Vell") not in ol["calls"]

    def test_a_key_held_by_another_spelling_is_used_but_not_copied(self, ol):
        AuthorFactory(name="M. Vell", open_library_key="OL9A")
        author = AuthorFactory(name="Mara Vell")
        BookFactory(open_library_key="OL3W", authors=[author])
        ol["works"]["OL3W"] = result("OL3W", AuthorRef("Mara Vell", "OL9A"))
        assert authors.resolve_author_key(author) == "OL9A"
        assert Author.objects.get(pk=author.pk).open_library_key is None

    def test_author_search_accepts_a_namesake_who_wrote_one_of_our_books(self, ol):
        author = AuthorFactory(name="Mara Vell")
        BookFactory(open_library_key=None, title="The Glass Orchard", authors=[author])
        ol["candidates"] = [
            AuthorCandidate("OL1A", "Mara Vell", work_count=50),  # a namesake
            AuthorCandidate("OL9A", "Vell, Mara", ("Mara Vell",), work_count=7),
            AuthorCandidate("OL2A", "Someone Else", work_count=99),
        ]
        ol["author_works"]["OL1A"] = [AuthorWork("OL5W", "Cooking for Two")]
        ol["author_works"]["OL9A"] = [AuthorWork("OL3W", "The Glass Orchard: A Novel")]
        assert authors.resolve_author_key(author) == "OL9A"
        tried = [c[1] for c in ol["calls"] if c[0] == "author_works"]
        assert tried == ["OL1A", "OL9A"]  # most works first; "Someone Else" never tried

    def test_no_confirmed_namesake_means_no_key(self, ol):
        author = AuthorFactory(name="Mara Vell")
        BookFactory(open_library_key=None, title="The Glass Orchard", authors=[author])
        ol["candidates"] = [AuthorCandidate("OL1A", "Mara Vell", work_count=50)]
        ol["author_works"]["OL1A"] = [AuthorWork("OL5W", "Cooking for Two")]
        assert authors.resolve_author_key(author) is None
        assert Author.objects.get(pk=author.pk).open_library_key is None

    def test_an_author_with_no_books_is_not_guessed(self, ol):
        assert authors.resolve_author_key(AuthorFactory(name="Mara Vell")) is None
        assert ol["calls"] == []


# --- Merging and grouping -------------------------------------------------------------


class TestAuthorWorksFor:
    def test_matches_catalog_books_by_key_then_title_and_adds_unlisted_ones(self, ol):
        author = AuthorFactory(name="Mara Vell", open_library_key="OL9A")
        by_key = BookFactory(open_library_key="OL3W", title="Orchard (Glass #1)", authors=[author])
        by_title = BookFactory(open_library_key=None, title="Salt Roads", authors=[author])
        unlisted = BookFactory(open_library_key=None, title="A Short Story", authors=[author])
        ol["author_works"][("OL9A", "editions")] = [
            AuthorWork("OL3W", "The Glass Orchard", 2019, edition_count=9),
            AuthorWork("OL7W", "Salt Roads", 2015),
        ]
        ol["author_works"][("OL9A", "new")] = [
            AuthorWork("OL7W", "Salt Roads", 2015),
            AuthorWork("OL8W", "Winter Ledger", 2026),  # only in the newest list
        ]
        items = authors.author_works_for(author, "OL9A")

        assert [(i.title, i.work_key, i.book_id) for i in items] == [
            ("Salt Roads", "OL7W", by_title.pk),
            ("Orchard (Glass #1)", "OL3W", by_key.pk),  # the catalog title wins
            ("Winter Ledger", "OL8W", None),
            ("A Short Story", None, unlisted.pk),
        ]

    def test_one_catalog_book_never_matches_two_works(self, ol):
        author = AuthorFactory(open_library_key="OL9A")
        BookFactory(open_library_key=None, title="Salt Roads", authors=[author])
        ol["author_works"]["OL9A"] = [
            AuthorWork("OL7W", "Salt Roads", 2015, edition_count=5),
            AuthorWork("OL8W", "Salt Roads!", 2020, edition_count=1),
        ]
        items = authors.author_works_for(author, "OL9A")
        assert sum(1 for i in items if i.book_id) == 1

    def test_without_a_key_lists_catalog_books_only(self, ol):
        author = AuthorFactory()
        book = BookFactory(authors=[author])
        assert [i.book_id for i in authors.author_works_for(author, None)] == [book.pk]
        assert ol["calls"] == []


class TestGroupBySeries:
    def test_series_in_number_order_then_the_rest_oldest_first(self):
        def item(title, year, series="", number=None, book_id=None):
            return authors.WorkItem(title, None, year, "", book_id, series, number)

        groups = authors.group_by_series(
            [
                item("Standalone B", 2021),
                item("Glass 2", 2020, "Glass", Decimal("2")),
                item("Salt 1", 2010, "Salt", Decimal("1"), book_id=5),
                item("Glass 1", 2019, "Glass", Decimal("1")),
                item("Standalone A", None),
                item("Glass novella", 2019, "Glass", Decimal("1.5")),
            ],
            {5: {"id": 9, "status": "finished"}},
        )
        assert [(g["series_name"], [w["title"] for w in g["works"]]) for g in groups] == [
            ("Salt", ["Salt 1"]),
            ("Glass", ["Glass 1", "Glass novella", "Glass 2"]),
            (None, ["Standalone B", "Standalone A"]),
        ]
        assert groups[0]["works"][0]["shelf"] == {"id": 9, "status": "finished"}
        assert groups[2]["works"][0]["shelf"] is None


# --- Author IDs for links -----------------------------------------------------------------


def test_author_ids_for_search_results():
    keyed = AuthorFactory(name="Mara Vell", open_library_key="OL9A")
    named = AuthorFactory(name="J. R. R. Tolkien")
    results = [
        BookResult(Source.OPEN_LIBRARY, "OL1W", "A", authors=(AuthorRef("M. Vell", "OL9A"),)),
        BookResult(
            Source.GOOGLE_BOOKS,
            "g1",
            "B",
            authors=(AuthorRef("J.R.R. Tolkien"), AuthorRef("Nobody Yet")),
        ),
        BookResult(Source.GOOGLE_BOOKS, "g2", "C"),
    ]
    assert authors.author_ids_for(results) == [[keyed.pk], [named.pk, None], []]


# --- Endpoint -----------------------------------------------------------------------


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def detail(author) -> str:
    return reverse("authors:author-detail", args=[author.pk])


class TestAuthorEndpoint:
    def test_requires_login(self, api_client):
        assert api_client.get(detail(AuthorFactory())).status_code == 401

    def test_unknown_author_is_404(self, client):
        assert client.get(reverse("authors:author-detail", args=[999999])).status_code == 404

    def test_works_with_shelf_status_grouped_by_series(self, client, user, ol):
        author = AuthorFactory(name="Mara Vell", open_library_key="OL9A")
        book = BookFactory(
            open_library_key="OL3W",
            title="The Glass Orchard",
            series_name="Glass",
            series_number=Decimal("1"),
            authors=[author],
        )
        entry = UserBookFactory(user=user, book=book, status=UserBook.Status.FINISHED)
        UserBookFactory(book=book)  # someone else's shelf: never shown
        ol["author_works"]["OL9A"] = [
            AuthorWork("OL3W", "The Glass Orchard", 2019, "https://covers/x.jpg"),
            AuthorWork("OL8W", "Winter Ledger", 2026),
        ]
        body = client.get(detail(author)).json()

        assert body["name"] == "Mara Vell" and body["open_library_key"] == "OL9A"
        assert body["open_library_url"] == "https://openlibrary.org/authors/OL9A"
        assert body["works_unavailable"] is False
        assert body["groups"] == [
            {
                "series_name": "Glass",
                "works": [
                    {
                        "title": "The Glass Orchard",
                        "work_key": "OL3W",
                        "first_publish_year": 2019,
                        "cover_url": book.cover_url or "https://covers/x.jpg",
                        "book_id": book.pk,
                        "series_name": "Glass",
                        "series_number": "1.0",
                        "shelf": {"id": entry.pk, "status": "finished"},
                    }
                ],
            },
            {
                "series_name": None,
                "works": [
                    {
                        "title": "Winter Ledger",
                        "work_key": "OL8W",
                        "first_publish_year": 2026,
                        "cover_url": "",
                        "book_id": None,
                        "series_name": None,
                        "series_number": None,
                        "shelf": None,
                    }
                ],
            },
        ]

    def test_open_library_down_still_lists_catalog_books(self, client, ol):
        author = AuthorFactory(name="Mara Vell")
        book = BookFactory(open_library_key="OL3W", authors=[author])
        ol["fail"] = True
        body = client.get(detail(author)).json()
        assert body["works_unavailable"] is True and body["open_library_url"] is None
        assert [w["book_id"] for g in body["groups"] for w in g["works"]] == [book.pk]

    def test_uses_the_search_throttle(self):
        from catalog.views import AuthorDetailView

        assert AuthorDetailView.throttle_scope == "book_search"

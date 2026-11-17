"""Catalog pieces added for the Goodreads import: title normalization, ISBN-13 coercion,
the Open Library throttle and batch ISBN search, and saving a result without a fetch."""

import pytest
from responses import matchers

from catalog.models import Book
from catalog.services import catalog, normalize, open_library
from catalog.services.types import AuthorRef, BookResult, Source

from .conftest import OL_SEARCH
from .factories import BookFactory


@pytest.mark.parametrize(
    ("title", "key"),
    [
        ("The Martian: A Novel", "the martian"),
        ("Leviathan Wakes (The Expanse, #1)", "leviathan wakes"),
        ("Project Hail Mary [Movie Tie-In]", "project hail mary"),
        ("Pride & Prejudice", "pride and prejudice"),
        ("Cien años de soledad", "cien anos de soledad"),
        ("  Don't   Panic!  ", "don t panic"),
        ("Collected Stories (Vol. 1) (Deluxe)", "collected stories"),
    ],
)
def test_normalize_title(title, key):
    assert normalize.normalize_title(title) == key


@pytest.mark.parametrize(
    ("a", "b", "compatible"),
    [
        ("Dune", "Dune", True),
        ("Dune", "Dune Messiah", True),  # prefix: still plausibly the same ISBN family
        ("The Glass Orchard", "Glass Orchard, The", True),  # word overlap
        ("Project Hail Mary", "La Mujer en el Kama Sutra", False),  # a real bad OL ISBN
        ("", "Dune", False),
    ],
)
def test_titles_compatible(a, b, compatible):
    assert normalize.titles_compatible(a, b) is compatible


@pytest.mark.parametrize(
    ("value", "expected"),
    [("9780593135204", "9780593135204"), ("0-593-13520-2", "9780593135204"), ("nope", "")],
)
def test_as_isbn_13(value, expected):
    assert normalize.as_isbn_13(value) == expected


class TestThrottle:
    def test_spaces_requests_to_the_configured_rate(self, settings, monkeypatch):
        settings.OPEN_LIBRARY_REQUESTS_PER_SECOND = 1
        clock = {"now": 100.0}
        sleeps: list[float] = []
        monkeypatch.setattr(open_library.time, "monotonic", lambda: clock["now"])

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        monkeypatch.setattr(open_library.time, "sleep", fake_sleep)
        monkeypatch.setattr(open_library, "_last_request_at", 0.0)

        open_library._throttle()  # first: no wait
        clock["now"] += 0.25
        open_library._throttle()  # 0.25s later: waits the remaining 0.75s
        assert sleeps == [pytest.approx(0.75)]

    def test_zero_disables_it(self, settings, monkeypatch):
        settings.OPEN_LIBRARY_REQUESTS_PER_SECOND = 0
        monkeypatch.setattr(open_library.time, "sleep", lambda s: pytest.fail("slept"))
        open_library._throttle()
        open_library._throttle()


class TestSearchByIsbns:
    def doc(self, key, title, isbns, author="Andy Weir"):
        return {"key": f"/works/{key}", "title": title, "author_name": [author], "isbn": isbns}

    def test_one_request_per_batch_and_isbn_set_to_the_match(self, mocked, monkeypatch):
        monkeypatch.setattr(open_library, "ISBN_BATCH_SIZE", 2)
        isbns = ["9780593135204", "9780441013593", "9780000000019"]
        mocked.get(
            OL_SEARCH,
            json={
                "docs": [
                    self.doc("OL1W", "Project Hail Mary", ["0593135202", "9781529157468"]),
                    self.doc("OL2W", "Dune", ["9780441013593"], "Frank Herbert"),
                ]
            },
            match=[matchers.query_param_matcher(open_library.isbn_batch_params(isbns[:2]))],
        )
        mocked.get(
            OL_SEARCH,
            json={"docs": []},
            match=[matchers.query_param_matcher(open_library.isbn_batch_params(isbns[2:]))],
        )

        found = open_library.search_by_isbns(isbns + ["9780593135204", ""])  # dupes, blanks

        assert len(mocked.calls) == 2  # 3 unique ISBNs at 2 per batch
        # The ISBN-10 in the doc matched the row's ISBN-13.
        assert [r.source_id for r in found["9780593135204"]] == ["OL1W"]
        assert found["9780593135204"][0].isbn_13 == "9780593135204"
        assert found["9780441013593"][0].title == "Dune"
        assert "9780000000019" not in found

    def test_query_shape(self):
        params = open_library.isbn_batch_params(["9780593135204", "9780441013593"])
        assert params["q"] == "isbn:(9780593135204 OR 9780441013593)"
        assert params["limit"] == 6

    def test_one_isbn_can_have_several_works(self, mocked):
        mocked.get(
            OL_SEARCH,
            json={
                "docs": [
                    self.doc("OL1W", "Dune", ["9780441013593"], "Frank Herbert"),
                    self.doc("OL2W", "Dune (Deluxe)", ["9780441013593"], "Frank Herbert"),
                ]
            },
        )
        found = open_library.search_by_isbns(["9780441013593"])
        assert [r.source_id for r in found["9780441013593"]] == ["OL1W", "OL2W"]


@pytest.mark.django_db
class TestSaveBookResult:
    def result(self, **overrides):
        values = {
            "source": Source.OPEN_LIBRARY,
            "source_id": "OL1W",
            "title": "Project Hail Mary",
            "authors": (AuthorRef("Andy Weir", "OL1A"),),
            "isbn_13": "9780593135204",
        }
        values.update(overrides)
        return BookResult(**values)

    def test_creates_without_any_request(self, mocked):
        book, created = catalog.save_book_result(self.result())
        assert created and book.open_library_key == "OL1W" and len(mocked.calls) == 0
        assert [a.name for a in book.authors.all()] == ["Andy Weir"]

    def test_same_source_id_returns_the_existing_book(self):
        existing = BookFactory(google_books_id=None, open_library_key="OL1W")
        assert catalog.save_book_result(self.result()) == (existing, False)

    def test_isbn_match_reuses_the_oldest_book(self):
        existing = BookFactory(isbn_13="9780593135204", open_library_key=None)
        book, created = catalog.save_book_result(self.result())
        assert (book, created) == (existing, False)
        book.refresh_from_db()
        assert book.open_library_key == "OL1W"
        assert Book.objects.count() == 1


def test_user_agent_follows_the_setting_even_after_the_session_exists(mocked, settings):
    """Regression: the cached session used to keep the User-Agent it was created with."""
    from responses import matchers as m

    open_library._session()  # create (or reuse) the cached session first
    settings.OPEN_LIBRARY_USER_AGENT = "Changed-UA/2.0"
    mocked.get(
        OL_SEARCH, json={"docs": []}, match=[m.header_matcher({"User-Agent": "Changed-UA/2.0"})]
    )
    assert open_library.search("anything") == []


def test_title_author_search_is_cached(mocked):
    mocked.get(
        OL_SEARCH,
        json={"docs": [{"key": "/works/OL1W", "title": "Dune", "author_name": ["Frank Herbert"]}]},
    )
    first = open_library.search_title_author("Dune", "Frank Herbert")
    second = open_library.search_title_author("dune", "frank herbert")
    assert first == second and first[0].source_id == "OL1W" and len(mocked.calls) == 1

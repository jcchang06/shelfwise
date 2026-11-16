import datetime as dt

import pytest
from responses import matchers

from catalog.dates import DatePrecision
from catalog.models import Author, Book
from catalog.services import catalog, open_library
from catalog.services.types import AuthorRef, BookNotFoundError, BookResult, Source

from .conftest import OL_SEARCH, google_volume_url, load_fixture, ol_work_url
from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db


def google_volume(volume_id="vol1", **info):
    info.setdefault("title", "Project Hail Mary")
    return {"id": volume_id, "volumeInfo": info}


def mock_google_volume(mocked, volume_id="vol1", **info):
    mocked.get(google_volume_url(volume_id), json=google_volume(volume_id, **info))


def mock_ol_work(mocked, work_key="OL1W", work=None, doc=None):
    mocked.get(ol_work_url(work_key), json=work or {"title": "Project Hail Mary"})
    mocked.get(
        OL_SEARCH,
        json={"docs": [doc] if doc else []},
        match=[matchers.query_param_matcher(open_library.work_search_params(work_key))],
    )


class TestCreate:
    def test_creates_book_from_google(self, mocked):
        body = load_fixture("google_volume")
        mocked.get(google_volume_url(body["id"]), json=body)

        book, created = catalog.get_or_create_book(Source.GOOGLE_BOOKS, body["id"])

        assert created
        assert book.google_books_id == body["id"] and book.open_library_key is None
        assert book.title and book.description and book.genres
        assert book.published_date is not None and book.published_date_precision
        assert list(book.authors.values_list("name", flat=True))

    def test_maps_partial_date(self, mocked):
        mock_google_volume(mocked, publishedDate="2014-03")
        book, _ = catalog.get_or_create_book("google_books", "vol1")
        assert book.published_date == dt.date(2014, 3, 1)
        assert book.published_date_precision == DatePrecision.MONTH

    def test_unparseable_date_saves_without_one(self, mocked):
        mock_google_volume(mocked, publishedDate="circa 1850")
        book, _ = catalog.get_or_create_book("google_books", "vol1")
        assert book.published_date is None and book.published_date_precision == ""

    def test_creates_book_from_open_library(self, mocked):
        mock_ol_work(
            mocked,
            work={"title": "The Dispossessed", "description": "An ambiguous utopia."},
            doc={
                "key": "/works/OL1W",
                "title": "The Dispossessed",
                "author_name": ["Ursula K. Le Guin"],
                "author_key": ["OL1A"],
                "first_publish_year": 1974,
            },
        )
        book, created = catalog.get_or_create_book(Source.OPEN_LIBRARY, "OL1W")
        assert created and book.open_library_key == "OL1W" and book.google_books_id is None
        assert book.description == "An ambiguous utopia."
        assert book.authors.get().open_library_key == "OL1A"

    def test_authors_linked_in_credit_order(self, mocked):
        mock_google_volume(mocked, authors=["Terry Pratchett", "Neil Gaiman"])
        book, _ = catalog.get_or_create_book("google_books", "vol1")
        ordered = [ba.author.name for ba in book.book_authors.order_by("position")]
        assert ordered == ["Terry Pratchett", "Neil Gaiman"]

    def test_duplicate_author_in_one_result_linked_once(self, mocked):
        mock_google_volume(mocked, authors=["Andy Weir", "Andy  Weir."])
        book, _ = catalog.get_or_create_book("google_books", "vol1")
        assert book.book_authors.count() == 1

    def test_not_found_propagates_and_saves_nothing(self, mocked):
        mocked.get(google_volume_url("missing"), status=404, json={})
        with pytest.raises(BookNotFoundError):
            catalog.get_or_create_book("google_books", "missing")
        assert not Book.objects.exists()

    def test_unknown_source_rejected(self):
        with pytest.raises(ValueError):
            catalog.get_or_create_book("goodreads", "1")


class TestExisting:
    def test_same_source_id_returns_book_without_calling_api(self, mocked):
        existing = BookFactory(google_books_id="vol1")
        book, created = catalog.get_or_create_book("google_books", "vol1")
        assert (book, created) == (existing, False)
        assert len(mocked.calls) == 0

    def test_isbn_match_reuses_book_and_fills_missing_id(self, mocked):
        existing = BookFactory(
            google_books_id=None, open_library_key="OL1W", isbn_13="9780593135204"
        )
        mock_google_volume(
            mocked, industryIdentifiers=[{"type": "ISBN_13", "identifier": "9780593135204"}]
        )
        book, created = catalog.get_or_create_book("google_books", "vol1")
        assert not created and book == existing
        book.refresh_from_db()
        assert book.google_books_id == "vol1" and book.open_library_key == "OL1W"
        assert Book.objects.count() == 1

    def test_isbn_match_uses_oldest_book(self, mocked):
        oldest = BookFactory(isbn_13="9780593135204", google_books_id="gbA")
        BookFactory(isbn_13="9780593135204", google_books_id="gbB")
        mock_google_volume(
            mocked, industryIdentifiers=[{"type": "ISBN_13", "identifier": "9780593135204"}]
        )
        book, created = catalog.get_or_create_book("google_books", "vol1")
        assert not created and book == oldest
        book.refresh_from_db()
        assert book.google_books_id == "gbA"  # an ID already set is never overwritten

    def test_isbn_match_fills_only_empty_fields(self, mocked):
        existing = BookFactory(
            google_books_id=None,
            isbn_13="9780593135204",
            title="Kept Title",
            description="",
            page_count=None,
            genres=[],
            cover_url="",
            published_date=None,
            published_date_precision="",
        )
        mock_google_volume(
            mocked,
            title="Ignored Title",
            description="New description",
            pageCount=496,
            categories=["Fiction"],
            publishedDate="2021",
            imageLinks={"thumbnail": "https://img/x"},
            industryIdentifiers=[{"type": "ISBN_13", "identifier": "9780593135204"}],
        )
        catalog.get_or_create_book("google_books", "vol1")
        existing.refresh_from_db()
        assert existing.title == "Kept Title"
        assert existing.description == "New description"
        assert existing.page_count == 496
        assert existing.genres == ["Fiction"]
        assert existing.cover_url == "https://img/x"
        assert existing.published_date == dt.date(2021, 1, 1)

    def test_isbn_match_without_authors_gets_them(self, mocked):
        BookFactory(isbn_13="9780593135204", google_books_id=None)
        mock_google_volume(
            mocked,
            authors=["Andy Weir"],
            industryIdentifiers=[{"type": "ISBN_13", "identifier": "9780593135204"}],
        )
        book, _ = catalog.get_or_create_book("google_books", "vol1")
        assert [a.name for a in book.authors.all()] == ["Andy Weir"]

    def test_book_without_isbn_never_isbn_matches(self, mocked):
        BookFactory(isbn_13="", google_books_id="other")
        mock_google_volume(mocked)
        _, created = catalog.get_or_create_book("google_books", "vol1")
        assert created


class TestAuthors:
    def test_matches_by_normalized_name(self):
        existing = AuthorFactory(name="J. R. R. Tolkien")
        assert catalog.get_or_create_author(AuthorRef("j r r  tolkien")) == existing
        assert Author.objects.count() == 1

    def test_periods_removed_not_turned_into_spaces(self):
        # "J.R.R." -> "jrr", which differs from "J. R. R." -> "j r r" (by design).
        AuthorFactory(name="J. R. R. Tolkien")
        catalog.get_or_create_author(AuthorRef("J.R.R. Tolkien"))
        assert Author.objects.count() == 2

    def test_name_match_prefers_oldest(self):
        oldest = AuthorFactory(name="Andy Weir")
        AuthorFactory(name="ANDY WEIR")
        assert catalog.get_or_create_author(AuthorRef("andy weir")) == oldest

    def test_matches_by_open_library_key_first(self):
        keyed = AuthorFactory(name="Ursula Le Guin", open_library_key="OL1A")
        assert catalog.get_or_create_author(AuthorRef("Ursula K. Le Guin", "OL1A")) == keyed

    def test_keyless_author_with_same_name_gets_the_key(self):
        existing = AuthorFactory(name="Andy Weir", open_library_key=None)
        author = catalog.get_or_create_author(AuthorRef("Andy Weir", "OL1A"))
        assert author == existing
        existing.refresh_from_db()
        assert existing.open_library_key == "OL1A"

    def test_same_name_with_a_different_key_is_a_different_author(self):
        AuthorFactory(name="John Smith", open_library_key="OL1A")
        author = catalog.get_or_create_author(AuthorRef("John Smith", "OL2A"))
        assert author.open_library_key == "OL2A"
        assert Author.objects.count() == 2

    def test_creates_with_clean_display_name(self):
        author = catalog.get_or_create_author(AuthorRef("Andy Weir"))
        assert author.name == "Andy Weir"


class TestCatalogIdsFor:
    def result(self, source, source_id, isbn=""):
        return BookResult(source=source, source_id=source_id, title="T", isbn_13=isbn)

    def test_maps_by_source_id_then_oldest_isbn(self):
        by_google = BookFactory(google_books_id="vol1", isbn_13="")
        by_ol = BookFactory(google_books_id=None, open_library_key="OL1W", isbn_13="")
        oldest = BookFactory(google_books_id="gbA", isbn_13="9780593135204")
        BookFactory(google_books_id="gbB", isbn_13="9780593135204")

        ids = catalog.catalog_ids_for(
            [
                self.result(Source.GOOGLE_BOOKS, "vol1"),
                self.result(Source.OPEN_LIBRARY, "OL1W"),
                self.result(Source.GOOGLE_BOOKS, "new", isbn="9780593135204"),
                self.result(Source.GOOGLE_BOOKS, "unknown"),
            ]
        )
        assert ids == [by_google.id, by_ol.id, oldest.id, None]

    def test_source_ids_do_not_cross_sources(self):
        BookFactory(google_books_id="OL1W")  # silly, but must not match an OL key
        ids = catalog.catalog_ids_for([self.result(Source.OPEN_LIBRARY, "OL1W")])
        assert ids == [None]

    def test_empty(self):
        assert catalog.catalog_ids_for([]) == []

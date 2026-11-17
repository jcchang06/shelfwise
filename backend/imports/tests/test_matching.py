"""Matching Goodreads rows to catalog books (I-1). All HTTP is mocked."""

import re

import pytest
import responses
from django.core.cache import cache
from responses import matchers

from accounts.tests.factories import UserFactory
from catalog.models import Book
from catalog.services import google_books, open_library
from catalog.tests.factories import AuthorFactory, BookFactory
from imports.budget import google_calls_used
from imports.matching import MatchPausedError, match_row, prefetch_isbns
from imports.models import GoodreadsImport, ImportRow

pytestmark = pytest.mark.django_db

M = ImportRow.MatchMethod
GOOGLE_SEARCH = re.compile(re.escape(f"{google_books.API_ROOT}/volumes") + r"(\?.*)?$")
OL_SEARCH = f"{open_library.API_ROOT}/search.json"


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def _api_settings(settings):
    settings.GOOGLE_BOOKS_API_KEY = "test-key"
    settings.IMPORT_GOOGLE_DAILY_BUDGET = 600


def row(**fields) -> ImportRow:
    goodreads_import = GoodreadsImport.objects.create(user=UserFactory())
    values = {
        "goodreads_import": goodreads_import,
        "row_number": 1,
        "goodreads_book_id": "1",
        "title": "Project Hail Mary",
        "author": "Andy Weir",
        "status": "finished",
    }
    values.update(fields)
    return ImportRow.objects.create(**values)


def ol_doc(key="OL1W", title="Project Hail Mary", isbns=("9780593135204",), author="Andy Weir"):
    return {
        "key": f"/works/{key}",
        "title": title,
        "author_name": [author],
        "author_key": ["OL1A"],
        "isbn": list(isbns),
    }


def google_item(volume_id="vol1", title="Project Hail Mary", authors=("Andy Weir",)):
    return {"id": volume_id, "volumeInfo": {"title": title, "authors": list(authors)}}


class TestCatalog:
    def test_by_isbn_uses_the_oldest_book_and_makes_no_requests(self, mocked):
        oldest = BookFactory(isbn_13="9780593135204")
        BookFactory(isbn_13="9780593135204")
        match = match_row(row(isbn_13="9780593135204"), {})
        assert (match.book, match.method) == (oldest, M.CATALOG_ISBN)
        assert len(mocked.calls) == 0

    def test_by_title_and_first_author(self, mocked):
        book = BookFactory(
            title="The Glass Orchard: A Novel", authors=[AuthorFactory(name="Mara Vell")]
        )
        match = match_row(row(title="The Glass Orchard", author="Mara Vell, Bram Sato"), {})
        assert (match.book, match.method) == (book, M.CATALOG_TITLE)
        assert len(mocked.calls) == 0

    def test_title_match_uses_author_normalization(self):
        book = BookFactory(title="The Hobbit", authors=[AuthorFactory(name="J. R. R. Tolkien")])
        assert match_row(row(title="The Hobbit", author="J.R.R. Tolkien"), {}).book == book

    def test_same_title_by_another_author_is_not_a_match(self, mocked):
        BookFactory(title="Project Hail Mary", authors=[AuthorFactory(name="Someone Else")])
        mocked.get(GOOGLE_SEARCH, json={"totalItems": 0})
        assert match_row(row(), {}).book is None


class TestOpenLibraryIsbn:
    def test_prefetch_batches_only_isbns_not_in_the_catalog(self, mocked):
        BookFactory(isbn_13="9780441013593")
        rows = [
            row(row_number=1, isbn_13="9780593135204"),
            row(row_number=2, isbn_13="9780441013593"),
            row(row_number=3),
        ]
        mocked.get(
            OL_SEARCH,
            json={"docs": [ol_doc()]},
            match=[matchers.query_param_matcher(open_library.isbn_batch_params(["9780593135204"]))],
        )
        found = prefetch_isbns(rows)
        assert list(found) == ["9780593135204"] and len(mocked.calls) == 1

    def test_prefetch_with_nothing_to_look_up_makes_no_request(self, mocked):
        assert prefetch_isbns([row()]) == {} and len(mocked.calls) == 0

    def test_prefetch_failure_is_not_fatal(self, mocked):
        mocked.get(OL_SEARCH, status=503)
        assert prefetch_isbns([row(isbn_13="9780593135204")]) == {}

    def test_isbn_hit_is_saved_from_the_batch_without_another_request(self, mocked):
        r = row(isbn_13="9780593135204")
        mocked.get(OL_SEARCH, json={"docs": [ol_doc()]})
        found = prefetch_isbns([r])
        calls_after_prefetch = len(mocked.calls)

        match = match_row(r, found)

        assert match.method == M.ISBN
        assert match.book.open_library_key == "OL1W" and match.book.isbn_13 == "9780593135204"
        assert len(mocked.calls) == calls_after_prefetch  # no work.json / single-book call

    def test_isbn_pointing_at_another_book_falls_through_to_title_search(self, mocked):
        r = row(isbn_13="9780000000019")
        found = {
            "9780000000019": [
                open_library.parse_search_doc(
                    ol_doc(title="La Mujer en el Kama Sutra", isbns=["9780000000019"])
                )
            ]
        }
        mocked.get(GOOGLE_SEARCH, json={"items": [google_item()]})
        match = match_row(r, found)
        assert match.method == M.TITLE_AUTHOR  # rescued by title + author

    def test_isbn_mismatch_is_explained_when_nothing_else_matches(self, mocked):
        r = row(isbn_13="9780000000019")
        found = {
            "9780000000019": [
                open_library.parse_search_doc(
                    ol_doc(title="La Mujer en el Kama Sutra", isbns=["9780000000019"])
                )
            ]
        }
        mocked.get(GOOGLE_SEARCH, json={"totalItems": 0})
        match = match_row(r, found)
        assert match.book is None
        assert "belongs to “La Mujer en el Kama Sutra” in Open Library" in match.note


class TestGoogleTitleAuthor:
    def test_exact_title_and_author_is_matched_and_saved(self, mocked):
        mocked.get(
            google_books.API_ROOT + "/volumes",
            json={"items": [google_item(title="Project Hail Mary: A Novel")]},
            match=[
                matchers.query_param_matcher(
                    {"q": 'intitle:"Project Hail Mary" inauthor:"Andy Weir"'}, strict_match=False
                )
            ],
        )
        match = match_row(row(), {})
        assert match.method == M.TITLE_AUTHOR and match.book.google_books_id == "vol1"
        assert google_calls_used() == 1
        assert len(mocked.calls) == 1  # saved from the search result: no get_volume call

    def test_near_misses_are_not_matched(self, mocked):
        mocked.get(
            GOOGLE_SEARCH,
            json={
                "items": [
                    google_item("v1", "Project Hail Mary Study Guide"),
                    google_item("v2", "Project Hail Mary", ("Summary Press",)),
                ]
            },
        )
        match = match_row(row(), {})
        assert match.book is None
        assert "none with this exact title and author" in match.note
        assert not Book.objects.exists()

    def test_first_author_can_be_any_of_the_results_authors(self, mocked):
        mocked.get(GOOGLE_SEARCH, json={"items": [google_item(authors=("Co Author", "Andy Weir"))]})
        assert match_row(row(), {}).method == M.TITLE_AUTHOR

    def test_no_author_means_no_title_search(self, mocked):
        match = match_row(row(author=""), {})
        assert match.book is None and match.note == "No author to search by."
        assert len(mocked.calls) == 0

    def test_budget_exhausted_pauses_without_a_request(self, mocked, settings):
        settings.IMPORT_GOOGLE_DAILY_BUDGET = 0
        with pytest.raises(MatchPausedError, match="budget"):
            match_row(row(), {})
        assert len(mocked.calls) == 0

    def test_google_quota_hit_pauses(self, mocked):
        mocked.get(GOOGLE_SEARCH, status=429, json={})
        with pytest.raises(MatchPausedError, match="quota"):
            match_row(row(), {})
        assert cache.get(google_books.QUOTA_FLAG_KEY) is True

    def test_google_down_is_unmatched_not_paused(self, mocked):
        mocked.get(GOOGLE_SEARCH, status=500)
        match = match_row(row(), {})
        assert match.book is None and "couldn't be reached" in match.note

    def test_a_second_row_matches_the_book_saved_for_the_first(self, mocked):
        mocked.get(GOOGLE_SEARCH, json={"items": [google_item()]})
        first = match_row(row(row_number=1), {})
        second = match_row(row(row_number=2, goodreads_book_id="2"), {})
        assert second.book == first.book and second.method == M.CATALOG_TITLE
        assert len(mocked.calls) == 1

"""Nightly metadata enrichment (C-6). Open Library calls are stubbed at the client
functions (get_work, search_by_isbns), whose HTTP side is tested in test_open_library.py
and test_import_support.py."""

import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from catalog.models import Author, Book
from catalog.services import enrichment, open_library
from catalog.services.types import (
    AuthorRef,
    BookNotFoundError,
    BookResult,
    BookSourceError,
    Source,
)

from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db
NOW = dt.datetime(2026, 11, 17, 10, 0, tzinfo=dt.UTC)


def work(key="OL1W", title="The Glass Orchard", **fields) -> BookResult:
    defaults = {
        "description": "A quiet novel about an orchard.",
        "genres": ("Literary Fiction",),
        "authors": (AuthorRef("Mara Vell", "OL9A"),),
    }
    return BookResult(Source.OPEN_LIBRARY, key, title, **{**defaults, **fields})


def bare_book(**fields) -> Book:
    """A book saved from Open Library search: no description or genres yet."""
    defaults = {
        "google_books_id": None,
        "open_library_key": "OL1W",
        "title": "The Glass Orchard",
        "description": "",
        "genres": [],
    }
    return BookFactory(**{**defaults, **fields})


@pytest.fixture
def ol(monkeypatch):
    """Stub Open Library: works by key, ISBN results, and a log of calls."""
    state = {"works": {}, "isbns": {}, "calls": [], "fail": False}

    def get_work(key):
        state["calls"].append(("work", key))
        if state["fail"]:
            raise BookSourceError("down")
        if key not in state["works"]:
            raise BookNotFoundError(key)
        return state["works"][key]

    def search_by_isbns(isbns):
        state["calls"].append(("isbns", tuple(isbns)))
        if state["fail"]:
            raise BookSourceError("down")
        return {i: state["isbns"][i] for i in isbns if i in state["isbns"]}

    monkeypatch.setattr(open_library, "get_work", get_work)
    monkeypatch.setattr(open_library, "search_by_isbns", search_by_isbns)
    monkeypatch.setattr(enrichment.time, "sleep", lambda seconds: None)
    return state


def refresh(book: Book) -> Book:
    book.refresh_from_db()
    return book


class TestFilling:
    def test_fills_missing_description_and_genres(self, ol):
        book = bare_book()
        ol["works"]["OL1W"] = work()
        report = enrichment.enrich_books(now=NOW)

        book = refresh(book)
        assert book.description == "A quiet novel about an orchard."
        assert book.genres == ["Literary Fiction"]
        assert book.enrichment_checked_at == NOW
        assert (report.checked, report.descriptions, report.genres) == (1, 1, 1)

    def test_never_overwrites_existing_data(self, ol):
        book = bare_book(description="My own summary.")  # genres still empty
        ol["works"]["OL1W"] = work()
        enrichment.enrich_books(now=NOW)

        book = refresh(book)
        assert book.description == "My own summary."
        assert book.genres == ["Literary Fiction"]

    def test_complete_books_are_not_looked_up(self, ol):
        BookFactory(open_library_key="OL1W")  # has a description and genres
        assert enrichment.enrich_books(now=NOW).checked == 0
        assert ol["calls"] == []

    def test_books_with_no_key_or_isbn_are_skipped(self, ol):
        bare_book(open_library_key=None, isbn_13="")
        assert enrichment.enrich_books(now=NOW).checked == 0
        assert enrichment.coverage().unreachable == 1


class TestRechecks:
    def test_not_found_is_marked_checked_and_left_for_30_days(self, ol):
        book = bare_book()  # no work stubbed: BookNotFoundError
        assert enrichment.enrich_books(now=NOW).not_found == 1
        assert refresh(book).enrichment_checked_at == NOW

        assert enrichment.enrich_books(now=NOW + dt.timedelta(days=29)).checked == 0
        assert enrichment.enrich_books(now=NOW + dt.timedelta(days=31)).checked == 1

    def test_a_work_with_nothing_to_add_is_also_left_for_30_days(self, ol):
        bare_book()
        ol["works"]["OL1W"] = work(description="", genres=())
        enrichment.enrich_books(now=NOW)
        assert enrichment.enrich_books(now=NOW + dt.timedelta(days=1)).checked == 0

    def test_never_checked_books_go_first(self, ol):
        old = bare_book(open_library_key="OL2W", enrichment_checked_at=NOW - dt.timedelta(days=40))
        new = bare_book(open_library_key="OL3W")
        enrichment.enrich_books(now=NOW, limit=1)
        assert refresh(new).enrichment_checked_at == NOW
        assert refresh(old).enrichment_checked_at != NOW


class TestIsbnLookup:
    def test_finds_and_saves_the_work_key_by_isbn(self, ol):
        book = bare_book(open_library_key=None, isbn_13="9780000000019")
        ol["isbns"]["9780000000019"] = [work("OL5W")]
        ol["works"]["OL5W"] = work("OL5W")
        report = enrichment.enrich_books(now=NOW)

        book = refresh(book)
        assert book.open_library_key == "OL5W"
        assert book.description
        assert report.work_keys == 1
        assert ol["calls"] == [("isbns", ("9780000000019",)), ("work", "OL5W")]

    def test_isbns_are_looked_up_in_batches(self, ol):
        for n in range(enrichment.ISBN_BATCH + 1):
            bare_book(open_library_key=None, isbn_13=f"978{n:010d}")
        enrichment.enrich_books(now=NOW)
        batches = [call for call in ol["calls"] if call[0] == "isbns"]
        assert [len(isbns) for _, isbns in batches] == [enrichment.ISBN_BATCH, 1]

    def test_ignores_an_isbn_that_points_at_another_title(self, ol):
        book = bare_book(open_library_key=None, isbn_13="9780000000019")
        ol["isbns"]["9780000000019"] = [work("OL5W", title="La Mujer en el Kama Sutra")]
        report = enrichment.enrich_books(now=NOW)

        book = refresh(book)
        assert book.open_library_key is None and book.description == ""
        assert report.not_found == 1 and book.enrichment_checked_at == NOW

    def test_a_work_key_already_in_the_catalog_is_not_copied(self, ol):
        BookFactory(open_library_key="OL5W")
        book = bare_book(open_library_key=None, isbn_13="9780000000019")
        ol["isbns"]["9780000000019"] = [work("OL5W")]
        ol["works"]["OL5W"] = work("OL5W")
        report = enrichment.enrich_books(now=NOW)

        book = refresh(book)
        assert book.open_library_key is None  # unique: left for merge_duplicate_books
        assert book.description  # still filled from the matching work
        assert report.duplicate_works == 1


class TestAuthorKeys:
    def test_fills_a_missing_author_key_by_name(self, ol):
        author = AuthorFactory(name="Mara  Vell")  # normalized names match
        bare_book(authors=[author])
        ol["works"]["OL1W"] = work()
        assert enrichment.enrich_books(now=NOW).author_keys == 1
        author.refresh_from_db()
        assert author.open_library_key == "OL9A"

    def test_leaves_other_authors_and_existing_keys_alone(self, ol):
        other = AuthorFactory(name="Someone Else")
        keyed = AuthorFactory(name="Mara Vell", open_library_key="OL1A")
        bare_book(authors=[other, keyed])
        ol["works"]["OL1W"] = work()
        enrichment.enrich_books(now=NOW)
        assert Author.objects.get(pk=other.pk).open_library_key is None
        assert Author.objects.get(pk=keyed.pk).open_library_key == "OL1A"

    def test_a_key_held_by_another_author_row_is_not_copied(self, ol):
        AuthorFactory(name="M. Vell", open_library_key="OL9A")
        author = AuthorFactory(name="Mara Vell")
        bare_book(authors=[author])
        ol["works"]["OL1W"] = work()
        assert enrichment.enrich_books(now=NOW).duplicate_authors == 1
        assert Author.objects.get(pk=author.pk).open_library_key is None


class TestFailures:
    def test_retries_three_times_then_leaves_the_book_for_next_run(self, ol):
        book = bare_book()
        ol["fail"] = True
        report = enrichment.enrich_books(now=NOW)

        assert ol["calls"] == [("work", "OL1W")] * 3
        assert report.failed == 1 and report.checked == 0
        assert refresh(book).enrichment_checked_at is None

    def test_a_retry_that_succeeds_counts_as_found(self, ol, monkeypatch):
        bare_book()
        ol["works"]["OL1W"] = work()
        attempts = {"n": 0}
        real = open_library.get_work

        def flaky(key):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise BookSourceError("blip")
            return real(key)

        monkeypatch.setattr(open_library, "get_work", flaky)
        assert enrichment.enrich_books(now=NOW).descriptions == 1

    def test_stops_when_open_library_looks_down(self, ol):
        for n in range(enrichment.MAX_CONSECUTIVE_FAILURES + 3):
            bare_book(open_library_key=f"OL{n + 10}W")
        ol["fail"] = True
        report = enrichment.enrich_books(now=NOW)

        assert report.failed == enrichment.MAX_CONSECUTIVE_FAILURES - 1
        assert "in a row" in report.stopped
        assert len(ol["calls"]) == enrichment.MAX_CONSECUTIVE_FAILURES * 3

    def test_stops_when_out_of_time_and_keeps_progress(self, ol, monkeypatch):
        first, second = bare_book(open_library_key="OL2W"), bare_book(open_library_key="OL3W")
        ol["works"]["OL2W"] = work("OL2W")
        ol["works"]["OL3W"] = work("OL3W")
        real = open_library.get_work
        clock = {"now": 0.0}

        def slow(key):
            clock["now"] += 100  # each lookup "takes" 100 seconds
            return real(key)

        monkeypatch.setattr(open_library, "get_work", slow)
        monkeypatch.setattr(enrichment.time, "monotonic", lambda: clock["now"])
        report = enrichment.enrich_books(stop_at=50, now=NOW)

        assert report.stopped == "out of time" and report.checked == 1
        assert refresh(first).enrichment_checked_at == NOW
        assert refresh(second).enrichment_checked_at is None


class TestCommand:
    def test_prints_counts_and_coverage_without_titles(self, ol, capsys):
        bare_book(title="Secret Title")
        bare_book(open_library_key="OL2W", title="Another Secret")
        BookFactory()  # complete
        ol["works"]["OL1W"] = work()
        call_command("enrich_books", "--max-minutes", "1")

        out = capsys.readouterr().out
        assert "Books looked up:              2" in out
        assert "descriptions filled:        1" in out
        assert "still without a description: 1 of 3 (33%)" in out
        assert "still without genres:        1 of 3 (33%)" in out
        assert "Secret" not in out

    def test_checked_at_does_not_bump_updated_at(self, ol):
        book = bare_book()
        before = refresh(book).updated_at
        enrichment.enrich_books(now=timezone.now())  # not found: only the check is saved
        assert refresh(book).updated_at == before

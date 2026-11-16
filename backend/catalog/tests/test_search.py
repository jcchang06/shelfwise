import pytest
import requests
from django.core.cache import cache

from catalog.services import google_books
from catalog.services.search import search_books
from catalog.services.types import BookSearchUnavailableError, Source

from .conftest import GOOGLE_SEARCH_RE, OL_SEARCH_RE, load_fixture


def test_uses_google_when_it_has_results(mocked):
    mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
    result = search_books("project hail mary")
    assert result.source == Source.GOOGLE_BOOKS and result.results
    assert all("openlibrary" not in call.request.url for call in mocked.calls)


def test_falls_back_when_google_finds_nothing(mocked):
    mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
    mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
    result = search_books("project hail mary")
    assert result.source == Source.OPEN_LIBRARY and result.results


def test_falls_back_when_google_errors(mocked):
    mocked.get(GOOGLE_SEARCH_RE, status=500)
    mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
    assert search_books("dune").source == Source.OPEN_LIBRARY


def test_falls_back_when_google_times_out(mocked):
    mocked.get(GOOGLE_SEARCH_RE, body=requests.Timeout())
    mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
    assert search_books("dune").source == Source.OPEN_LIBRARY


def test_goes_straight_to_open_library_while_quota_flag_is_set(mocked):
    cache.set(google_books.QUOTA_FLAG_KEY, True)
    mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
    assert search_books("dune").source == Source.OPEN_LIBRARY
    assert len(mocked.calls) == 1


def test_empty_google_answer_beats_open_library_error(mocked):
    mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
    mocked.get(OL_SEARCH_RE, status=503)
    result = search_books("qzxqv")
    assert result.source == Source.GOOGLE_BOOKS and result.results == []


def test_both_empty_returns_open_library_empty(mocked):
    mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
    mocked.get(OL_SEARCH_RE, json={"docs": []})
    result = search_books("qzxqv")
    assert result.results == [] and result.source == Source.OPEN_LIBRARY


def test_both_failing_raises_unavailable(mocked):
    mocked.get(GOOGLE_SEARCH_RE, status=500)
    mocked.get(OL_SEARCH_RE, status=500)
    with pytest.raises(BookSearchUnavailableError):
        search_books("dune")

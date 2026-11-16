import datetime as dt
import re

import pytest
import requests
import responses
from django.core.cache import cache
from responses import matchers

from catalog.services import google_books
from catalog.services.types import (
    BookNotFoundError,
    BookSourceError,
    QuotaExceededError,
    Source,
)

from .conftest import GOOGLE_SEARCH_RE, GOOGLE_VOLUMES, google_volume_url, load_fixture

HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def volume(**info):
    return {"id": info.pop("id", "vol1"), "volumeInfo": {"title": "A Book", **info}}


class TestSearch:
    def test_parses_results(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        results = google_books.search("project hail mary")

        assert results
        first = results[0]
        assert first.source == Source.GOOGLE_BOOKS
        assert first.source_id and first.title

    def test_sends_expected_params(self, mocked):
        mocked.get(
            GOOGLE_VOLUMES,
            json={"totalItems": 0},
            match=[
                matchers.query_param_matcher(
                    {
                        "q": "dune",
                        "startIndex": "20",
                        "maxResults": "20",
                        "printType": "books",
                        "langRestrict": "en",
                        "key": "test-key",
                    }
                )
            ],
        )
        assert google_books.search("dune", page=2) == []

    def test_language_comes_from_settings(self, mocked, settings):
        settings.BOOK_SEARCH_LANGUAGE = "fr"
        mocked.get(
            GOOGLE_VOLUMES,
            json={"totalItems": 0},
            match=[matchers.query_param_matcher({"langRestrict": "fr"}, strict_match=False)],
        )
        google_books.search("dune")

    def test_omits_key_when_unset(self, mocked, settings):
        settings.GOOGLE_BOOKS_API_KEY = ""
        mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
        google_books.search("dune")
        assert "key=" not in mocked.calls[0].request.url

    def test_isbn_query_uses_isbn_prefix(self, mocked):
        mocked.get(
            GOOGLE_VOLUMES,
            json=load_fixture("google_search_isbn"),
            match=[matchers.query_param_matcher({"q": "isbn:9780593135204"}, strict_match=False)],
        )
        results = google_books.search("978-0-593-13520-4")
        assert results[0].isbn_13 == "9780593135204"

    def test_no_items_key_means_no_results(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search_empty"))
        assert google_books.search("qzxqv") == []

    def test_cached_by_normalized_query(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        first = google_books.search("Project  Hail Mary")
        second = google_books.search("project hail mary ")
        assert first == second
        assert len(mocked.calls) == 1

    def test_pages_cached_separately(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, json={"totalItems": 0})
        google_books.search("dune", page=1)
        google_books.search("dune", page=2)
        assert len(mocked.calls) == 2

    def test_skips_items_without_id_or_title(self, mocked):
        body = {"items": [{"volumeInfo": {"title": "No ID"}}, {"id": "x", "volumeInfo": {}}]}
        mocked.get(GOOGLE_SEARCH_RE, json=body)
        assert google_books.search("dune") == []


class TestErrors:
    def test_server_error_retried_once_then_succeeds(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, status=503)
        mocked.get(GOOGLE_SEARCH_RE, json=load_fixture("google_search"))
        assert google_books.search("dune")
        assert len(mocked.calls) == 2

    def test_persistent_server_error_raises(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, status=503)
        with pytest.raises(BookSourceError):
            google_books.search("dune")
        assert len(mocked.calls) == 2  # first try + one retry

    def test_failures_are_not_cached(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, status=500)
        with pytest.raises(BookSourceError):
            google_books.search("dune")
        mocked.replace(responses.GET, GOOGLE_SEARCH_RE, json={"totalItems": 0})
        assert google_books.search("dune") == []

    def test_timeout_raises_source_error(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, body=requests.Timeout("slow"))
        with pytest.raises(BookSourceError):
            google_books.search("dune")

    def test_non_json_raises_source_error(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, body="<html>oops</html>")
        with pytest.raises(BookSourceError):
            google_books.search("dune")

    def test_error_message_never_contains_api_key(self, mocked):
        mocked.get(GOOGLE_SEARCH_RE, body="not json")
        with pytest.raises(BookSourceError) as exc_info:
            google_books.search("dune")
        assert "test-key" not in str(exc_info.value)


class TestQuota:
    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (429, {"error": {"code": 429}}),
            (403, {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}),
        ],
        ids=["429", "403-dailyLimitExceeded"],
    )
    def test_quota_error_sets_shared_flag(self, mocked, status, body):
        mocked.get(GOOGLE_SEARCH_RE, status=status, json=body)
        with pytest.raises(QuotaExceededError):
            google_books.search("dune")
        assert cache.get(google_books.QUOTA_FLAG_KEY) is True

    def test_other_403_is_not_quota(self, mocked):
        body = {"error": {"errors": [{"reason": "forbidden"}]}}
        mocked.get(GOOGLE_SEARCH_RE, status=403, json=body)
        with pytest.raises(BookSourceError) as exc_info:
            google_books.search("dune")
        assert not isinstance(exc_info.value, QuotaExceededError)
        assert not google_books.quota_exhausted()

    def test_flag_skips_google_without_a_request(self, mocked):
        cache.set(google_books.QUOTA_FLAG_KEY, True)
        with pytest.raises(QuotaExceededError):
            google_books.search("dune")
        with pytest.raises(QuotaExceededError):
            google_books.get_volume("vol1")
        assert len(mocked.calls) == 0

    @pytest.mark.parametrize(
        ("now_utc", "expected_seconds"),
        [
            # 23:00 PST (UTC-8) -> one hour to midnight
            (dt.datetime(2026, 11, 17, 7, 0, tzinfo=dt.UTC), 3600),
            # 00:30 PDT (UTC-7), summer -> 23.5 hours
            (dt.datetime(2026, 7, 1, 7, 30, tzinfo=dt.UTC), 23 * 3600 + 1800),
        ],
    )
    def test_flag_lasts_until_midnight_pacific(self, now_utc, expected_seconds):
        assert google_books.seconds_until_quota_reset(now_utc) == expected_seconds

    def test_flag_lasts_at_least_a_minute(self):
        just_before = dt.datetime(2026, 11, 17, 7, 59, 59, tzinfo=dt.UTC)  # 23:59:59 PST
        assert google_books.seconds_until_quota_reset(just_before) == 60


class TestGetVolume:
    def test_parses_and_caches(self, mocked):
        body = load_fixture("google_volume")
        mocked.get(google_volume_url(body["id"]), json=body)
        first = google_books.get_volume(body["id"])
        second = google_books.get_volume(body["id"])
        assert first == second and first.source_id == body["id"]
        assert len(mocked.calls) == 1

    def test_sends_key(self, mocked):
        mocked.get(
            google_volume_url("vol1"),
            json=volume(),
            match=[matchers.query_param_matcher({"key": "test-key"})],
        )
        google_books.get_volume("vol1")

    def test_404_raises_not_found(self, mocked):
        mocked.get(google_volume_url("missing"), status=404, json={"error": {"code": 404}})
        with pytest.raises(BookNotFoundError):
            google_books.get_volume("missing")

    def test_volume_without_title_is_not_found(self, mocked):
        mocked.get(google_volume_url("vol1"), json={"id": "vol1", "volumeInfo": {}})
        with pytest.raises(BookNotFoundError):
            google_books.get_volume("vol1")


class TestParseVolume:
    def test_maps_every_field(self):
        result = google_books.parse_volume(
            volume(
                id="abc",
                title="Dune &amp; Friends",
                authors=["Frank Herbert", " ", "Brian Herbert"],
                description="<p>Spice &amp; sand.</p>",
                categories=["Fiction / Science Fiction / General"],
                pageCount=412,
                publishedDate="1965-08",
                industryIdentifiers=[
                    {"type": "ISBN_10", "identifier": "0441013597"},
                    {"type": "ISBN_13", "identifier": "9780441013593"},
                ],
                imageLinks={"thumbnail": "http://books.google.com/x?id=abc&edge=curl"},
            )
        )
        assert result is not None
        assert result.source_id == "abc"
        assert result.title == "Dune & Friends"
        assert [a.name for a in result.authors] == ["Frank Herbert", "Brian Herbert"]
        assert all(a.open_library_key is None for a in result.authors)
        assert result.description == "Spice & sand."
        assert result.genres == ("Fiction", "Science Fiction")
        assert result.page_count == 412
        assert result.published_date == "1965-08"
        assert result.isbn_13 == "9780441013593"
        assert result.cover_url == "https://books.google.com/x?id=abc"

    def test_missing_optional_fields(self):
        result = google_books.parse_volume(volume(pageCount=0))
        assert result is not None
        assert result.authors == () and result.genres == ()
        assert result.page_count is None  # Google uses 0 for "unknown"
        assert result.isbn_13 == "" and result.cover_url == "" and result.description == ""

    def test_falls_back_to_small_thumbnail(self):
        result = google_books.parse_volume(
            volume(imageLinks={"smallThumbnail": "http://books.google.com/s"})
        )
        assert result is not None and result.cover_url == "https://books.google.com/s"


@pytest.mark.parametrize("name", ["google_search", "google_search_isbn"])
def test_recorded_search_fixtures_parse(name):
    """Contract check on recorded responses: every item maps to a clean BookResult."""
    items = load_fixture(name).get("items", [])
    results = [google_books.parse_volume(item) for item in items]
    assert results and all(results)
    for r in results:
        assert r.title
        assert r.isbn_13 == "" or len(r.isbn_13) == 13
        assert r.cover_url == "" or r.cover_url.startswith("https://")
        assert not HTML_TAG.search(r.description)


def test_recorded_volume_fixture_parses():
    result = google_books.parse_volume(load_fixture("google_volume"))
    assert result is not None and result.title and result.authors


class TestRecordedResponses:
    """Raw-vs-parsed checks on the recorded fixtures. They compare what the API actually
    sent with what we store, so they keep working when the fixtures are re-recorded."""

    def test_volume_description_html_is_cleaned(self):
        raw = load_fixture("google_volume")["volumeInfo"].get("description", "")
        result = google_books.parse_volume(load_fixture("google_volume"))
        assert result is not None
        if HTML_TAG.search(raw):
            assert not HTML_TAG.search(result.description)
        if "<br><br>" in raw or "</p><p>" in raw:
            assert "\n\n" in result.description  # paragraphs survive as blank lines
        assert not re.search(r"&(#\d+|[a-z]+);", result.description)

    def test_volume_categories_split_into_genres(self):
        categories = load_fixture("google_volume")["volumeInfo"].get("categories", [])
        result = google_books.parse_volume(load_fixture("google_volume"))
        assert result is not None
        expected_parts = {
            part.strip() for c in categories for part in c.split("/") if part.strip() != "General"
        }
        assert set(result.genres) == expected_parts
        assert all("/" not in genre for genre in result.genres)

    def test_search_isbns_come_from_isbn_13_identifiers(self):
        for item in load_fixture("google_search").get("items", []):
            identifiers = item["volumeInfo"].get("industryIdentifiers", [])
            isbn_13s = [i["identifier"] for i in identifiers if i["type"] == "ISBN_13"]
            result = google_books.parse_volume(item)
            assert result is not None
            # One of the volume's own ISBN-13s (English preferred when several), or none.
            assert result.isbn_13 in isbn_13s if isbn_13s else result.isbn_13 == ""

import pytest
import requests
from responses import matchers

from catalog.services import open_library
from catalog.services.types import AuthorRef, BookNotFoundError, BookSourceError, Source

from .conftest import OL_SEARCH, OL_SEARCH_RE, load_fixture, ol_work_url


def work_key_of(fixture: str) -> str:
    return load_fixture(fixture)["docs"][0]["key"].rsplit("/", 1)[-1]


class TestSearch:
    def test_parses_results(self, mocked):
        mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
        results = open_library.search("project hail mary")
        assert results
        assert results[0].source == Source.OPEN_LIBRARY
        assert results[0].source_id == work_key_of("ol_search")

    def test_sends_expected_params_and_user_agent(self, mocked):
        mocked.get(
            OL_SEARCH,
            json={"docs": []},
            match=[
                matchers.query_param_matcher(
                    {
                        "q": "dune",
                        "page": "2",
                        "limit": "20",
                        "fields": open_library.SEARCH_FIELDS,
                        "lang": "en",
                    }
                ),
                matchers.header_matcher({"User-Agent": "Shelfwise-tests/0.1"}),
            ],
        )
        assert open_library.search("dune", page=2) == []

    def test_isbn_query(self, mocked):
        mocked.get(
            OL_SEARCH,
            json={"docs": []},
            match=[matchers.query_param_matcher({"q": "isbn:9780593135204"}, strict_match=False)],
        )
        open_library.search("978-0593135204")

    def test_empty(self, mocked):
        mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search_empty"))
        assert open_library.search("qzxqv") == []

    def test_cached(self, mocked):
        mocked.get(OL_SEARCH_RE, json=load_fixture("ol_search"))
        open_library.search("Dune")
        open_library.search("dune")
        assert len(mocked.calls) == 1

    def test_errors_become_source_error(self, mocked):
        mocked.get(OL_SEARCH_RE, body=requests.ConnectionError("down"))
        with pytest.raises(BookSourceError):
            open_library.search("dune")


class TestParseSearchDoc:
    def test_maps_fields(self):
        result = open_library.parse_search_doc(
            {
                "key": "/works/OL1W",
                "title": "The Left Hand of Darkness",
                "author_name": ["Ursula K. Le Guin", "Harold Bloom"],
                "author_key": ["OL1A"],  # shorter than author_name: second gets no key
                "first_publish_year": 1969,
                "number_of_pages_median": 304,
                "isbn": ["0441478123", "9780441478125"],
                "subject": ["Science fiction", "Accessible book", "Gender"],
                "cover_i": 42,
            }
        )
        assert result is not None
        assert result.source_id == "OL1W"
        assert result.authors == (
            AuthorRef("Ursula K. Le Guin", "OL1A"),
            AuthorRef("Harold Bloom", None),
        )
        assert result.published_date == "1969"
        assert result.page_count == 304
        assert result.isbn_13 == "9780441478125"
        assert result.genres == ("Science fiction", "Gender")
        assert result.cover_url == "https://covers.openlibrary.org/b/id/42-L.jpg"
        assert result.description == ""  # search docs never include one

    def test_minimal_doc(self):
        result = open_library.parse_search_doc({"key": "/works/OL1W", "title": "X"})
        assert result is not None
        assert result.authors == () and result.published_date == "" and result.cover_url == ""

    @pytest.mark.parametrize("doc", [{"title": "No key"}, {"key": "/works/OL1W"}])
    def test_incomplete_doc_skipped(self, doc):
        assert open_library.parse_search_doc(doc) is None


class TestGetWork:
    def register(self, mocked, work_key, work=None, docs=None):
        mocked.get(ol_work_url(work_key), json=work if work is not None else {})
        mocked.get(
            OL_SEARCH,
            json={"docs": docs if docs is not None else []},
            match=[matchers.query_param_matcher(open_library.work_search_params(work_key))],
        )

    def test_merges_work_description_with_search_doc(self, mocked):
        key = work_key_of("ol_work_search")
        mocked.get(ol_work_url(key), json=load_fixture("ol_work"))
        mocked.get(OL_SEARCH_RE, json=load_fixture("ol_work_search"))

        result = open_library.get_work(key)

        assert result.source_id == key
        assert result.authors  # from the search doc
        assert result.description  # from the work
        assert "&mdash;" not in result.description and "\r" not in result.description

    @pytest.mark.parametrize(
        "description",
        ["Plain <i>text</i>.", {"type": "/type/text", "value": "Plain <i>text</i>."}],
        ids=["string", "typed-object"],
    )
    def test_description_formats(self, mocked, description):
        self.register(
            mocked,
            "OL1W",
            work={"title": "X", "description": description},
            docs=[{"key": "/works/OL1W", "title": "X"}],
        )
        assert open_library.get_work("OL1W").description == "Plain text."

    def test_work_only_when_search_finds_nothing(self, mocked):
        self.register(
            mocked,
            "OL1W",
            work={"title": "Orphan Work", "subjects": ["Poetry"], "covers": [-1, 7]},
        )
        result = open_library.get_work("OL1W")
        assert result.title == "Orphan Work"
        assert result.genres == ("Poetry",)
        assert result.cover_url.endswith("/7-L.jpg")  # -1 means "no cover"; skipped

    def test_ignores_search_doc_for_a_different_work(self, mocked):
        self.register(
            mocked,
            "OL1W",
            work={"title": "Right"},
            docs=[{"key": "/works/OL2W", "title": "Wrong", "author_name": ["Nope"]}],
        )
        result = open_library.get_work("OL1W")
        assert result.title == "Right" and result.authors == ()

    def test_404_raises_not_found(self, mocked):
        mocked.get(ol_work_url("OL404W"), status=404, json={"error": "notfound"})
        with pytest.raises(BookNotFoundError):
            open_library.get_work("OL404W")

    def test_work_without_title_is_not_found(self, mocked):
        self.register(mocked, "OL1W", work={})
        with pytest.raises(BookNotFoundError):
            open_library.get_work("OL1W")

    def test_cached(self, mocked):
        self.register(mocked, "OL1W", work={"title": "X"})
        open_library.get_work("OL1W")
        open_library.get_work("OL1W")
        assert len(mocked.calls) == 2  # work + search once, then cache


def test_recorded_search_fixture_parses():
    docs = load_fixture("ol_search")["docs"]
    results = [open_library.parse_search_doc(d) for d in docs]
    assert results and all(results)
    for r in results:
        assert r.isbn_13 == "" or len(r.isbn_13) == 13
        assert r.cover_url == "" or r.cover_url.startswith("https://")
        assert len(r.genres) <= open_library.normalize.MAX_OPEN_LIBRARY_GENRES

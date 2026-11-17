"""Building the catalog seed (C-3) from tiny fake Open Library dumps."""

import dataclasses
import gzip
import json
from pathlib import Path

import pytest
from django.core.management import call_command

from catalog.seed import build, dumps
from catalog.services.types import BookSourceError
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db
LONG = "A careful, quiet story about an orchard and the people who keep it. " * 4  # 200+
YEAR = 2026


def write_gz(path: Path, lines: list[str]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def work_line(n: int, title: str, **record) -> str:
    data = {
        "title": title,
        "description": {"type": "/type/text", "value": LONG},
        "subjects": ["Fantasy"],
        "authors": [{"author": {"key": f"/authors/OL{n}A"}, "type": {"key": "/type/author_role"}}],
        "covers": [100 + n],
        **record,
    }
    return f"/type/work\t/works/OL{n}W\t3\t2026-01-01T00:00:00\t{json.dumps(data)}"


def author_line(n: int, name: str) -> str:
    data = {"name": name, "key": f"/authors/OL{n}A"}
    return f"/type/author\t/authors/OL{n}A\t1\t2026-01-01T00:00:00\t{json.dumps(data)}"


def log_lines(n: int, readers: int, shelf: str = "Already Read") -> list[str]:
    return [f"/works/OL{n}W\t\\N\t{shelf}\t2026-08-28"] * readers


@pytest.fixture
def dumps_dir(tmp_path):
    """Works 1-6 by popularity (6 readers for OL1W down to 1 for OL6W)."""
    log = []
    for n, readers in zip(range(1, 7), range(6, 0, -1), strict=True):
        log += log_lines(n, readers)
    log += log_lines(6, 50, "Stopped Reading")  # DNFs never count
    write_gz(tmp_path / "ol_dump_reading-log_2026-10-31.txt.gz", log)
    write_gz(tmp_path / "ol_dump_ratings_2026-10-31.txt.gz", ["/works/OL5W\t\\N\t4\t2020-01-01"])
    write_gz(
        tmp_path / "ol_dump_works_2026-10-31.txt.gz",
        [
            work_line(1, "Salt Roads", subjects=["Romance"]),
            work_line(2, "Winter Ledger"),
            work_line(3, "Glass Houses", subjects=["Romance", "Fiction"]),
            work_line(4, "Short One", description="Too short."),
            work_line(5, "No Genres", subjects=["Accessible book", "Protected DAISY"]),
            work_line(6, "Least Popular"),
            "not\ta\tvalid\tline",
        ],
    )
    write_gz(
        tmp_path / "ol_dump_authors_2026-10-31.txt.gz",
        [author_line(n, f"Author {n}") for n in range(1, 7)],
    )
    return tmp_path


def details(years=None, languages=("eng",), missing=()):
    """A fake open_library.work_details."""
    years = years or {}
    calls = []

    def fetch(keys):
        calls.append(list(keys))
        return {
            key: {
                "first_publish_year": years.get(key, 2001),
                "page_count": 320,
                "isbn_13": f"978{key[2:-1].zfill(10)}",
                "languages": languages,
            }
            for key in keys
            if key not in missing
        }

    fetch.calls = calls
    return fetch


def run(dumps_dir, target=4, genres=(), candidates=100, **kwargs):
    snapshot = dataclasses.replace(build.read_snapshot(), genres=list(genres))
    return build.build_seed(
        dumps_dir,
        target=target,
        candidates=candidates,
        snapshot=snapshot,
        this_year=YEAR,
        fetch_details=kwargs.pop("fetch", details()),
        fetch_recent=kwargs.pop("recent", lambda *args: {}),
        sleep=lambda s: None,
        **kwargs,
    )


class TestDumps:
    def test_reading_log_counts_readers_but_not_stopped_reading(self, dumps_dir):
        counts = dumps.reading_log_counts(dumps.find_dump(dumps_dir, "reading-log"))
        assert counts[1] == 6 and counts[6] == 1

    def test_key_ids(self):
        assert dumps.key_id("/works/OL82563W") == 82563
        assert dumps.key_id("OL9A", "A") == 9
        assert dumps.key_id("/books/OL1M") is None
        assert dumps.key_id("OLxW") is None

    def test_missing_dump(self, tmp_path):
        with pytest.raises(dumps.DumpError, match="ol_dump_works"):
            dumps.find_dump(tmp_path, "works")

    def test_records_parse_only_wanted_lines(self, dumps_dir):
        found = dict(dumps.records(dumps.find_dump(dumps_dir, "works"), {2, 3}, "W"))
        assert sorted(found) == [2, 3] and found[2]["title"] == "Winter Ledger"


class TestCleanDescription:
    def test_markdown_links_and_trailing_sections_are_removed(self):
        raw = (
            "**A novel** about [an orchard](https://example.com/x) and [Mara][1].\n\n"
            "([source][1])\n\n[1]: https://example.com/src\n"
            "----------\nAlso contained in:\n- [Big Omnibus](/works/OL1W)"
        )
        assert build.clean_seed_description({"value": raw}) == (
            "A novel about an orchard and Mara."
        )

    def test_work_lists_without_a_separator_are_removed(self):
        raw = (
            "A thriller set in the Arctic.\n\nContains:\n"
            "[Deception Point [1/2]](https://openlibrary.org/works/OL2W)\n\n"
            "Also contained in:\n[Box Set](https://openlibrary.org/works/OL3W)"
        )
        assert build.clean_seed_description(raw) == "A thriller set in the Arctic."

    def test_nested_brackets_in_link_text_and_escaped_dividers(self):
        raw = "Read [Part One [1/2]](https://x.org/a) first.\n\n\\--------- *Then the novel.*"
        cleaned = build.clean_seed_description(raw)
        assert cleaned.startswith("Read Part One [1/2] first.")
        assert cleaned.endswith("Then the novel.*")
        assert "](" not in cleaned and "---" not in cleaned

    def test_real_dashes_in_prose_are_kept(self):
        raw = "Elantris: gigantic, beautiful, radiant-----filled with light. " * 5
        assert "radiant-----filled" in build.clean_seed_description(raw)

    def test_non_text_is_empty(self):
        assert build.clean_seed_description(None) == ""
        assert build.clean_seed_description({"type": "/type/text"}) == ""


class TestBuild:
    def test_filters_and_ranks_by_popularity(self, dumps_dir):
        books, report = run(dumps_dir, target=10)
        assert [b.work_key for b in books] == ["OL1W", "OL2W", "OL3W", "OL6W"]
        assert (report.short_description, report.no_genres) == (1, 1)
        first = books[0]
        assert first.authors == [{"key": "OL1A", "name": "Author 1"}]
        assert first.cover_url.endswith("/101-L.jpg")
        assert (first.first_publish_year, first.page_count, first.popularity) == (2001, 320, 6)
        assert report.shortfalls["total"] == 6

    def test_search_runs_in_batches_of_100_and_only_for_parsed_works(self, dumps_dir, monkeypatch):
        monkeypatch.setattr(build.open_library, "WORK_BATCH_SIZE", 2)
        fetch = details()
        run(dumps_dir, fetch=fetch)
        assert fetch.calls == [["OL1W", "OL2W"], ["OL3W", "OL6W"]]

    def test_drops_other_languages_and_works_search_doesnt_know(self, dumps_dir):
        books, report = run(dumps_dir, fetch=details(languages=("spa",)))
        assert books == [] and report.other_language == 4
        books, report = run(dumps_dir, fetch=details(missing={"OL1W"}))
        assert "OL1W" not in [b.work_key for b in books] and report.not_in_search == 1

    def test_skips_works_already_in_the_catalog(self, dumps_dir):
        BookFactory(open_library_key="OL1W")  # same key
        BookFactory(isbn_13="9780000000002")  # same ISBN as OL2W
        BookFactory(title="Glass Houses: A Novel", authors=[AuthorFactory(name="Author 3")])
        books, report = run(dumps_dir, target=10)
        assert [b.work_key for b in books] == ["OL6W"]
        assert report.already_in_catalog == 1 and report.duplicate_of_catalog == 2

    def test_keeps_the_most_popular_copy_of_a_work(self, dumps_dir):
        lines = [
            work_line(1, "Salt Roads"),
            work_line(
                2,
                "Salt Roads (Anniversary Edition)",
                authors=[{"author": {"key": "/authors/OL1A"}}],
            ),
        ]
        write_gz(dumps_dir / "ol_dump_works_2026-10-31.txt.gz", lines)
        books, report = run(dumps_dir, target=10)
        assert [b.work_key for b in books] == ["OL1W"] and report.duplicate_in_seed == 1

    def test_a_batch_that_keeps_failing_is_dropped_and_counted(self, dumps_dir, monkeypatch):
        monkeypatch.setattr(build.open_library, "WORK_BATCH_SIZE", 2)
        attempts = []
        good = details()

        def flaky(keys):
            attempts.append(list(keys))
            if "OL1W" in keys:
                raise BookSourceError("ConnectTimeout")
            return good(keys)

        books, report = run(dumps_dir, target=10, fetch=flaky)
        assert len([a for a in attempts if "OL1W" in a]) == 1 + len(build.RETRY_DELAYS)
        assert report.lookup_failed == 2  # OL1W and OL2W shared the failing batch
        assert [b.work_key for b in books] == ["OL3W", "OL6W"]

    def test_a_batch_that_recovers_on_retry_loses_nothing(self, dumps_dir):
        good, failed_once = details(), []

        def blip(keys):
            if not failed_once:
                failed_once.append(True)
                raise BookSourceError("ConnectTimeout")
            return good(keys)

        books, report = run(dumps_dir, target=10, fetch=blip)
        assert report.lookup_failed == 0 and len(books) == 4

    def test_the_recent_list_failing_is_reported_not_fatal(self, dumps_dir):
        def down(*args):
            raise BookSourceError("down")

        books, report = run(dumps_dir, target=10, recent=down)
        assert report.recent_list_failed and len(books) == 4

    def test_never_queries_the_database_after_the_snapshot(self, dumps_dir, monkeypatch):
        from django.db import connection

        snapshot = build.read_snapshot()

        def closed(*args, **kwargs):
            raise AssertionError("the build touched the database after the snapshot")

        monkeypatch.setattr(connection, "cursor", closed)
        monkeypatch.setattr(connection, "ensure_connection", closed)
        books, _ = build.build_seed(
            dumps_dir,
            10,
            100,
            snapshot,
            this_year=YEAR,
            fetch_details=details(),
            fetch_recent=lambda *a: {},
            sleep=lambda s: None,
        )
        assert len(books) == 4


class TestRecentCandidates:
    def test_adds_recent_works_beyond_the_top_n_ranked_by_search_readers(self, dumps_dir):
        asked = []

        def recent(from_year, to_year, count):
            asked.append((from_year, to_year, count))
            return {"OL6W": 900, "OL1W": 5, "OL999W": 3}  # OL1W is already a candidate

        fetch = details(years={"OL6W": 2025})
        books, report = run(dumps_dir, target=10, candidates=2, recent=recent, fetch=fetch)
        assert asked == [(2024, 2026, build.RECENT_CANDIDATES)]
        assert report.recent_candidates == 2  # OL6W, plus OL999W (not in the works dump)
        assert [b.work_key for b in books] == ["OL6W", "OL1W", "OL2W"]
        assert books[0].pool == "recent" and books[0].popularity == 900


class TestPools:
    def test_recent_then_taste_then_popular(self, dumps_dir, monkeypatch):
        monkeypatch.setattr(build, "RECENT_SHARE", 0.25)  # 1 of 4
        monkeypatch.setattr(build, "TASTE_SHARE", 0.25)  # 1 of 4
        fetch = details(years={"OL6W": 2024, "OL2W": 2023})  # 2024+ is "recent" in 2026
        books, report = run(dumps_dir, target=4, genres=["romance"], fetch=fetch)
        pools = {b.work_key: b.pool for b in books}
        assert pools == {"OL6W": "recent", "OL1W": "taste", "OL2W": "popular", "OL3W": "popular"}
        assert report.pools == {"recent": 1, "taste": 1, "popular": 2}
        assert report.recent_from_year == 2024 and report.shortfalls == {}

    def test_a_short_pool_is_filled_from_popular_and_reported(self, dumps_dir):
        books, report = run(dumps_dir, target=4, genres=[])
        assert report.pools == {"popular": 4}
        # 10% of 4 rounds to 0 recent; the 1 taste slot had no genres to match.
        assert report.shortfalls == {"taste": 1}


class TestTasteGenres:
    def test_finished_and_reading_rated_3_or_unrated_never_dnf(self):
        def entry(status, genres, rating=None):
            UserBookFactory(status=status, rating=rating, book=BookFactory(genres=genres))

        S = UserBook.Status
        entry(S.FINISHED, ["Romance", "Fiction"], rating=5)
        entry(S.FINISHED, ["romance", "Fantasy"])
        entry(S.READING, ["Mystery"])
        entry(S.FINISHED, ["Horror"], rating=2)  # disliked
        entry(S.WANT_TO_READ, ["Poetry"])
        UserBookFactory(status=S.DNF, dnf_reason="pacing", book=BookFactory(genres=["Western"]))
        assert build.taste_genres() == ["romance", "fantasy", "mystery"]  # ties A-Z


class TestCommand:
    def test_writes_the_seed_and_prints_counts_only(self, dumps_dir, monkeypatch, capsys):
        monkeypatch.setattr(build.open_library, "work_details", details())
        monkeypatch.setattr(build.open_library, "popular_recent_work_keys", lambda *a: {})
        out = dumps_dir / "seed.jsonl.gz"
        call_command(
            "build_catalog_seed", "--dumps", str(dumps_dir), "--out", str(out), "--target", "3"
        )

        printed = capsys.readouterr().out
        assert "Seed: 3 of 3 books" in printed and "popular:  3" in printed
        assert "Salt Roads" not in printed  # titles never printed
        with gzip.open(out, "rt", encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle]
        assert [r["work_key"] for r in records] == ["OL1W", "OL2W", "OL3W"]
        assert set(records[0]) >= {"title", "authors", "description", "genres", "pool"}

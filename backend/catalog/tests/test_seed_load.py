"""Loading and removing the catalog seed (C-3), and the read-only seed build."""

import gzip
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection
from django.db.backends.signals import connection_created

from catalog.models import Author, Book
from catalog.seed import load
from catalog.seed.readonly import read_only_database, release_connection
from tracking.tests.factories import ReadingLogFactory, UserBookFactory

from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db


def record(n: int, title: str | None = None, authors=None, **fields) -> dict:
    return {
        "work_key": f"OL{n}W",
        "title": title or f"Seed Book {n}",
        "authors": authors or [{"key": f"OL{n}A", "name": f"Seed Author {n}"}],
        "description": "A long enough description. " * 10,
        "genres": ["Fantasy"],
        "cover_url": f"https://covers.openlibrary.org/b/id/{n}-L.jpg",
        "first_publish_year": 2001,
        "page_count": 320,
        "isbn_13": f"978{n:010d}",
        "popularity": 10,
        "ratings": 1,
        "pool": "popular",
        **fields,
    }


@pytest.fixture
def seed_file(tmp_path):
    def write(records: list[dict]):
        path = tmp_path / "seed.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for r in records:
                handle.write(json.dumps(r) + "\n")
        return path

    return write


class TestLoad:
    def test_creates_books_and_authors_marked_as_seeded(self, seed_file):
        path = seed_file([record(1), record(2, pool="recent", first_publish_year=2025)])
        report = load.load_seed(path)

        book = Book.objects.get(open_library_key="OL1W")
        assert book.seeded_at is not None and book.genres == ["Fantasy"]
        assert (book.page_count, book.isbn_13, book.published_date.year) == (
            320,
            "9780000000001",
            2001,
        )
        assert [ba.author.open_library_key for ba in book.book_authors.all()] == ["OL1A"]
        assert (report.created, report.authors_created) == (2, 2)
        assert report.pools == {"popular": 1, "recent": 1}

    def test_dry_run_writes_nothing_but_reports_the_same_counts(self, seed_file):
        path = seed_file([record(1), record(2)])
        planned = load.load_seed(path, dry_run=True)
        assert Book.objects.count() == 0 and Author.objects.count() == 0
        loaded = load.load_seed(path)
        assert (planned.created, planned.authors_created) == (
            loaded.created,
            loaded.authors_created,
        )

    def test_running_it_again_adds_nothing(self, seed_file):
        path = seed_file([record(1), record(2)])
        load.load_seed(path)
        again = load.load_seed(path)
        assert again.created == 0 and again.existing_key == 2
        assert Book.objects.count() == 2 and Author.objects.count() == 2

    def test_skips_books_already_in_the_catalog(self, seed_file):
        BookFactory(isbn_13="9780000000001")  # same ISBN as record 1
        BookFactory(
            title="Seed Book 2: A Novel", isbn_13="", authors=[AuthorFactory(name="Seed Author 2")]
        )
        BookFactory(open_library_key="OL3W", isbn_13="")
        report = load.load_seed(seed_file([record(1), record(2), record(3), record(4)]))
        assert (report.existing_isbn, report.existing_title_author, report.existing_key) == (
            1,
            1,
            1,
        )
        assert report.created == 1

    def test_skips_a_second_copy_within_the_file_and_invalid_records(self, seed_file):
        report = load.load_seed(
            seed_file(
                [
                    record(1),
                    record(
                        9, title="Seed Book 1", authors=[{"key": "OL1A", "name": "Seed Author 1"}]
                    ),
                    {"work_key": "nope", "title": "x", "authors": []},
                ]
            )
        )
        assert (report.created, report.existing_title_author, report.invalid) == (1, 1, 1)

    def test_authors_match_by_key_then_keyless_name(self, seed_file):
        keyed = AuthorFactory(name="Someone", open_library_key="OL1A")
        keyless = AuthorFactory(name="J. R. R. Tolkien", open_library_key=None)
        path = seed_file(
            [
                record(1),  # OL1A: the keyed author, despite another name
                record(2, authors=[{"key": "OL2A", "name": "J.R.R. Tolkien"}]),
                record(3, authors=[{"key": "OL2A", "name": "J.R.R. Tolkien"}]),
            ]
        )
        planned = load.load_seed(path, dry_run=True)
        report = load.load_seed(path)
        assert Book.objects.get(open_library_key="OL1W").authors.get() == keyed
        keyless.refresh_from_db()
        assert keyless.open_library_key == "OL2A"  # given its key, not duplicated
        assert Book.objects.get(open_library_key="OL3W").authors.get() == keyless
        assert (report.authors_created, report.authors_keyed) == (0, 1)
        assert (planned.authors_created, planned.authors_keyed) == (0, 1)

    def test_loads_in_batches(self, seed_file, monkeypatch):
        monkeypatch.setattr(load, "BATCH_SIZE", 2)
        messages = []
        load.load_seed(seed_file([record(n) for n in range(1, 6)]), progress=messages.append)
        assert Book.objects.count() == 5
        assert messages == ["Loaded 2 of 5 books", "Loaded 4 of 5 books", "Loaded 5 of 5 books"]


class TestRemove:
    def test_removes_only_unshelved_unlogged_seed_books_and_orphaned_authors(self, seed_file):
        shared = {"key": "OL50A", "name": "Shared Author"}
        load.load_seed(
            seed_file(
                [
                    record(1),
                    record(2),
                    record(3),
                    record(4, authors=[shared]),
                    record(5, authors=[shared]),
                ]
            )
        )
        UserBookFactory(book=Book.objects.get(open_library_key="OL2W"))  # shelved: stays
        ReadingLogFactory(book=Book.objects.get(open_library_key="OL3W"))  # logged: stays
        UserBookFactory(book=Book.objects.get(open_library_key="OL4W"))  # keeps Shared Author
        mine = BookFactory(open_library_key="OL99W")  # not seeded: never removed

        plan = load.removal_plan()
        assert sorted(
            Book.objects.filter(pk__in=plan.book_ids).values_list("open_library_key", flat=True)
        ) == ["OL1W", "OL5W"]
        assert list(
            Author.objects.filter(pk__in=plan.author_ids).values_list("open_library_key", flat=True)
        ) == ["OL1A"]

        assert load.remove_seed(plan) == (2, 1)
        assert Book.objects.filter(pk=mine.pk).exists()
        assert Author.objects.filter(open_library_key="OL50A").exists()

    def test_the_token_changes_when_the_plan_does(self, seed_file):
        load.load_seed(seed_file([record(1), record(2)]))
        before = load.removal_plan().token
        UserBookFactory(book=Book.objects.get(open_library_key="OL1W"))
        assert load.removal_plan().token != before


class TestCommands:
    def test_load_prints_the_database_first(self, seed_file, capsys):
        call_command("seed_catalog", str(seed_file([record(1)])), "--dry-run")
        out = capsys.readouterr().out
        assert out.startswith("Database: ")
        assert "Would add books:                  1" in out and "nothing was changed" in out
        assert Book.objects.count() == 0

    def test_load(self, seed_file, capsys):
        call_command("seed_catalog", str(seed_file([record(1)])))
        assert "Added books:                  1" in capsys.readouterr().out
        assert Book.objects.filter(seeded_at__isnull=False).count() == 1

    def test_remove_needs_a_dry_run_token(self, seed_file, capsys):
        load.load_seed(seed_file([record(1)]))
        with pytest.raises(CommandError, match="--remove --dry-run first"):
            call_command("seed_catalog", "--remove")
        with pytest.raises(CommandError, match="changed since"):
            call_command("seed_catalog", "--remove", "--apply", "wrong")

        call_command("seed_catalog", "--remove", "--dry-run")
        out = capsys.readouterr().out
        assert out.startswith("Database: ") and "Would remove 1 seeded book(s)" in out
        token = out.rsplit("--apply ", 1)[1].strip()
        call_command("seed_catalog", "--remove", "--apply", token)
        assert Book.objects.count() == 0

    def test_load_needs_a_file(self):
        with pytest.raises(CommandError, match="Give the seed file"):
            call_command("seed_catalog")


class TestReadOnlyBuild:
    def test_writes_fail_while_the_database_is_read_only(self):
        with pytest.raises(DatabaseError, match="read-only transaction"):
            with read_only_database():
                Book.objects.create(title="Should not be saved")

    def test_reads_work_and_the_session_is_reset_afterwards(self):
        BookFactory()
        with read_only_database():
            assert Book.objects.count() == 1
            with connection.cursor() as cursor:
                cursor.execute("SHOW default_transaction_read_only")
                assert cursor.fetchone()[0] == "on"
        with connection.cursor() as cursor:
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone()[0] == "off"

    def test_connections_opened_during_the_block_are_read_only_too(self):
        with read_only_database():
            assert connection_created.has_listeners()
            ids = [r[0] for r in connection_created.receivers]
            assert any("catalog.seed.readonly" in str(i) for i in ids)
        assert not any("catalog.seed.readonly" in str(r[0]) for r in connection_created.receivers)

    def test_release_closes_the_connection_outside_a_transaction(self):
        closed = []
        in_transaction = SimpleNamespace(in_atomic_block=True, close=lambda: closed.append(1))
        release_connection(in_transaction)  # tests run inside one: left alone
        assert closed == []
        autocommit = SimpleNamespace(in_atomic_block=False, close=lambda: closed.append(1))
        release_connection(autocommit)  # how the command runs
        assert closed == [1]

    def test_build_command_reads_up_front_then_never_touches_the_database(
        self, tmp_path, monkeypatch, capsys
    ):
        """A long build must not hold, or reopen, a database session (Neon ends sessions
        idle in a transaction). After the up-front read the connection counts as closed."""
        from catalog.management.commands import build_catalog_seed as command
        from catalog.seed import build

        def closed(*args, **kwargs):
            raise AssertionError("the build touched the database after the snapshot")

        def release():
            monkeypatch.setattr(connection, "cursor", closed)
            monkeypatch.setattr(connection, "ensure_connection", closed)

        monkeypatch.setattr(command, "release_connection", release)
        monkeypatch.setattr(command, "read_only_database", _no_reset_read_only)
        monkeypatch.setattr(
            command, "build_seed", lambda *a, **k: ([], build.BuildReport(target=1))
        )
        call_command(
            "build_catalog_seed", "--dumps", str(tmp_path), "--out", str(tmp_path / "s.gz")
        )
        out = capsys.readouterr().out
        assert out.startswith("Database: ") and "Seed: 0 of 1 books" in out


@contextmanager
def _no_reset_read_only():
    """read_only_database without the closing reset (the test's cursor is 'closed')."""
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    yield

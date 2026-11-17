from pathlib import Path

import pytest
from django.db import IntegrityError

from accounts.tests.factories import UserFactory
from imports.csv_parser import ImportFileError
from imports.models import GoodreadsImport, GoodreadsLink, ImportRow
from imports.services import create_import
from tracking.tests.factories import UserBookFactory

pytestmark = pytest.mark.django_db

SAMPLE = (Path(__file__).parent / "fixtures" / "synthetic_goodreads.csv").read_bytes()


def test_create_import_stores_parsed_rows():
    user = UserFactory()
    goodreads_import = create_import(user, SAMPLE)

    assert goodreads_import.user == user
    assert goodreads_import.status == GoodreadsImport.Status.PENDING
    assert goodreads_import.total_rows == 12
    rows = list(goodreads_import.rows.all())
    assert [r.row_number for r in rows] == list(range(1, 13))
    first = rows[0]
    assert (first.title, first.series_name, first.isbn_13, first.rating) == (
        "The Glass Orchard",
        "Lanternfall",
        "9780000000019",
        5,
    )
    assert first.state == ImportRow.State.PENDING


def test_bad_rows_are_failed_and_counted_as_processed():
    goodreads_import = create_import(UserFactory(), SAMPLE)
    failed = goodreads_import.rows.filter(state=ImportRow.State.FAILED)
    assert sorted(r.row_number for r in failed) == [10, 11]  # duplicate, no title
    assert goodreads_import.failed_count == goodreads_import.processed_rows == 2
    assert failed.get(row_number=11).title == "(untitled)"


def test_notes_are_kept_on_rows():
    goodreads_import = create_import(UserFactory(), SAMPLE)
    assert "rating wasn't imported" in goodreads_import.rows.get(row_number=3).note


def test_unusable_file_saves_nothing():
    with pytest.raises(ImportFileError):
        create_import(UserFactory(), b"Title,Author\nDune,Frank Herbert\n")
    assert not GoodreadsImport.objects.exists() and not ImportRow.objects.exists()


def test_private_notes_never_reach_the_database():
    goodreads_import = create_import(UserFactory(), SAMPLE)
    values = [str(v) for row in goodreads_import.rows.values() for v in row.values()]
    assert not any("PRIVATE" in v for v in values)


def test_imports_belong_to_their_user():
    a, b = UserFactory(), UserFactory()
    create_import(a, SAMPLE)
    assert GoodreadsImport.objects.filter(user=b).count() == 0
    a.delete()
    assert not GoodreadsImport.objects.exists() and not ImportRow.objects.exists()


class TestModels:
    def test_row_number_unique_per_import(self):
        goodreads_import = create_import(UserFactory(), SAMPLE)
        with pytest.raises(IntegrityError):
            ImportRow.objects.create(
                goodreads_import=goodreads_import,
                row_number=1,
                goodreads_book_id="x",
                title="x",
                status="want_to_read",
            )

    def test_row_rating_range(self):
        goodreads_import = create_import(UserFactory(), SAMPLE)
        with pytest.raises(IntegrityError):
            ImportRow.objects.create(
                goodreads_import=goodreads_import,
                row_number=99,
                goodreads_book_id="x",
                title="x",
                status="finished",
                rating=6,
            )

    def test_one_link_per_user_and_goodreads_book(self):
        entry = UserBookFactory()
        GoodreadsLink.objects.create(
            user=entry.user,
            goodreads_book_id="9000001",
            user_book=entry,
            synced_at=entry.updated_at,
        )
        with pytest.raises(IntegrityError):
            GoodreadsLink.objects.create(
                user=entry.user,
                goodreads_book_id="9000001",
                user_book=UserBookFactory(user=entry.user),
                synced_at=entry.updated_at,
            )

    def test_two_goodreads_editions_can_link_to_one_entry(self):
        entry = UserBookFactory()
        for goodreads_id in ("1", "2"):
            GoodreadsLink.objects.create(
                user=entry.user,
                goodreads_book_id=goodreads_id,
                user_book=entry,
                synced_at=entry.updated_at,
            )
        assert entry.goodreads_links.count() == 2

    def test_removing_the_shelf_entry_removes_its_links(self):
        entry = UserBookFactory()
        GoodreadsLink.objects.create(
            user=entry.user, goodreads_book_id="1", user_book=entry, synced_at=entry.updated_at
        )
        entry.delete()
        assert not GoodreadsLink.objects.exists()

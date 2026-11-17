"""merge_duplicate_books: grouping, conflicts, the dry-run token, and merging."""

import datetime as dt
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.tests.factories import UserFactory
from catalog.models import Book
from catalog.services.duplicates import find_duplicate_groups, merge_group, plan_token
from imports.models import ImportRow
from imports.services import create_import
from tracking.models import ReadingLog, UserBook
from tracking.tests.factories import ReadingLogFactory, UserBookFactory

from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db


PAIR_IDS = iter(range(1, 1000))


def pair(title_a="The Martian", title_b="The Martian: A Novel", author_b="Andy Weir", **b):
    """An older and a newer copy of the same book, from different sources (unique IDs)."""
    n = next(PAIR_IDS)
    keeper = BookFactory(
        title=title_a,
        google_books_id=f"gb{n}",
        open_library_key=None,
        isbn_13=f"97805534{n:05d}",
        description="",
        authors=[AuthorFactory(name="Andy Weir")],
    )
    dup = BookFactory(
        title=title_b,
        google_books_id=None,
        open_library_key=f"OL{n}W",
        isbn_13=f"97808041{n:05d}",
        description="Stranded on Mars.",
        authors=[AuthorFactory(name=author_b)],
        **b,
    )
    return keeper, dup


def run(*args) -> str:
    out = StringIO()
    call_command("merge_duplicate_books", *args, stdout=out)
    return out.getvalue()


class TestGrouping:
    def test_groups_by_normalized_title_and_first_author(self):
        keeper, dup = pair(author_b="ANDY  WEIR")
        BookFactory(title="Artemis", authors=[AuthorFactory(name="Andy Weir")])  # different book
        [group] = find_duplicate_groups()
        assert group.keeper == keeper and group.duplicates == [dup]
        assert group.mergeable

    def test_series_and_edition_notes_are_ignored(self):
        pair(title_a="Leviathan Wakes", title_b="Leviathan Wakes (The Expanse, #1)")
        assert len(find_duplicate_groups()) == 1

    def test_different_authors_are_not_duplicates(self):
        pair(author_b="Someone Else")
        assert find_duplicate_groups() == []

    def test_books_without_authors_are_never_grouped(self):
        BookFactory(title="Untitled")
        BookFactory(title="Untitled")
        assert find_duplicate_groups() == []

    def test_one_user_on_two_copies_is_a_conflict(self):
        keeper, dup = pair()
        user = UserFactory()
        UserBookFactory(user=user, book=keeper)
        ReadingLogFactory(user=user, book=dup)
        [group] = find_duplicate_groups()
        assert not group.mergeable
        assert "has shelf entries or logs on books" in group.conflicts[0]

    def test_different_users_on_each_copy_is_fine(self):
        keeper, dup = pair()
        UserBookFactory(book=keeper)
        UserBookFactory(book=dup)
        assert find_duplicate_groups()[0].mergeable


class TestCommand:
    def test_refuses_without_a_mode(self):
        with pytest.raises(CommandError, match="--dry-run first"):
            run()

    def test_dry_run_reports_and_changes_nothing(self):
        keeper, dup = pair()
        out = run("--dry-run")
        assert f"keep   #{keeper.id}" in out and f"merge  #{dup.id}" in out
        assert "Nothing was changed." in out
        assert f"--apply {plan_token(find_duplicate_groups())}" in out
        assert Book.objects.count() == 2

    def test_dry_run_with_no_duplicates(self):
        assert "No duplicate books found" in run("--dry-run")

    def test_apply_needs_the_current_plan_token(self):
        pair()
        token = plan_token(find_duplicate_groups())
        BookFactory(title="The Martian", authors=[AuthorFactory(name="Andy Weir")])  # plan changes
        with pytest.raises(CommandError, match="changed since that dry run"):
            run("--apply", token)
        assert Book.objects.count() == 3

    def test_apply_merges_and_skips_conflicts(self):
        pair()
        conflicted_keeper, conflicted_dup = pair(title_a="Artemis", title_b="Artemis")
        user = UserFactory()
        UserBookFactory(user=user, book=conflicted_keeper)
        UserBookFactory(user=user, book=conflicted_dup)
        out = run("--apply", plan_token(find_duplicate_groups()))
        assert "Merged 1 duplicate book(s) into 1 keeper(s). Skipped 1 group(s)" in out
        assert Book.objects.filter(title__startswith="Artemis").count() == 2  # untouched

    def test_dry_run_marks_conflicts(self):
        keeper, dup = pair()
        user = UserFactory()
        UserBookFactory(user=user, book=keeper)
        UserBookFactory(user=user, book=dup)
        out = run("--dry-run")
        assert "NOT MERGED" in out and "--apply" not in out


class TestMerge:
    def test_moves_references_fills_gaps_and_deletes_the_duplicate(self):
        keeper, dup = pair()
        reader = UserFactory()
        entry = UserBookFactory(user=reader, book=dup, status=UserBook.Status.READING)
        ReadingLogFactory(user=reader, book=dup, log_date=dt.date(2026, 11, 1))
        [group] = find_duplicate_groups()

        merge_group(group)

        assert not Book.objects.filter(pk=dup.pk).exists()
        keeper.refresh_from_db()
        entry.refresh_from_db()
        assert entry.book == keeper
        assert ReadingLog.objects.get(user=reader).book == keeper
        assert keeper.description == "Stranded on Mars."  # was empty: filled
        assert keeper.google_books_id.startswith("gb") and keeper.open_library_key.startswith("OL")
        assert keeper.isbn_13.startswith("97805534")  # kept its own ISBN
        assert [a.name for a in keeper.authors.all()] == ["Andy Weir"]

    def test_import_rows_follow_the_merge(self):
        keeper, dup = pair()
        sample = (
            b"Book Id,Title,Author,ISBN,ISBN13,My Rating,Exclusive Shelf,Bookshelves,"
            b"Date Read,Date Added\n1,The Martian,Andy Weir,,,0,to-read,,,\n"
        )
        row = create_import(UserFactory(), sample).rows.get()
        ImportRow.objects.filter(pk=row.pk).update(book=dup)
        merge_group(find_duplicate_groups()[0])
        row.refresh_from_db()
        assert row.book == keeper

    def test_refuses_a_conflicted_group(self):
        keeper, dup = pair()
        user = UserFactory()
        UserBookFactory(user=user, book=keeper)
        UserBookFactory(user=user, book=dup)
        with pytest.raises(ValueError):
            merge_group(find_duplicate_groups()[0])


def test_merge_fills_missing_date_and_isbn_and_moves_authors():
    from catalog.dates import DatePrecision
    from catalog.models import BookAuthor

    keeper = BookFactory(
        title="Kindred",
        isbn_13="",
        published_date=None,
        published_date_precision="",
        google_books_id="gbK",
        authors=[AuthorFactory(name="Octavia E. Butler")],
    )
    dup = BookFactory(
        title="Kindred",
        isbn_13="9780807083697",
        published_date=dt.date(1979, 1, 1),
        published_date_precision=DatePrecision.YEAR,
        google_books_id=None,
        open_library_key="OLK1W",
        authors=[AuthorFactory(name="Octavia E Butler")],
    )
    [group] = find_duplicate_groups()
    # Drop the keeper's author link so the duplicate's authors must move over.
    BookAuthor.objects.filter(book=keeper).delete()
    merge_group(group)

    keeper.refresh_from_db()
    assert keeper.isbn_13 == "9780807083697"
    assert keeper.published_date == dt.date(1979, 1, 1)
    assert keeper.published_date_precision == DatePrecision.YEAR
    assert [a.name for a in keeper.authors.all()] == ["Octavia E Butler"]
    assert not Book.objects.filter(pk=dup.pk).exists()

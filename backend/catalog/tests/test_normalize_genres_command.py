"""normalize_genres: re-normalize stored genres (dry run, then apply)."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from catalog.models import Book

from .factories import BookFactory

pytestmark = pytest.mark.django_db


def test_dry_run_reports_before_and_after_and_writes_nothing(capsys):
    joined = BookFactory(genres=["Fiction, romance, general", "Romance"])
    BookFactory(genres=["Fiction"])
    BookFactory(genres=["Fantasy"])  # already clean
    call_command("normalize_genres", "--dry-run")
    out = capsys.readouterr().out
    assert out.startswith("Database: ")
    assert "Books whose genres change:            2" in out
    assert "Books with a joined value (, or /):       1        0" in out
    assert "Books with no genres:                     0        1" in out
    assert "Dry run: nothing was changed." in out
    joined.refresh_from_db()
    assert joined.genres == ["Fiction, romance, general", "Romance"]


def test_apply_rewrites_and_a_second_run_changes_nothing(capsys):
    joined = BookFactory(genres=["Fiction, Romance, Contemporary"])
    call_command("normalize_genres", "--apply")
    joined.refresh_from_db()
    assert joined.genres == ["Romance", "Contemporary"]
    capsys.readouterr()
    call_command("normalize_genres", "--dry-run")
    assert "Books whose genres change:            0" in capsys.readouterr().out


def test_needs_a_mode():
    with pytest.raises(CommandError, match="--dry-run first"):
        call_command("normalize_genres")
    assert Book.objects.count() == 0

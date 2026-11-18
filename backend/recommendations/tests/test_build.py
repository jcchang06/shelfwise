"""The nightly build's database side: snapshot, writing runs, and the two commands."""

import pytest
from django.core.management import call_command
from django.db import connection

from catalog.tests.factories import AuthorFactory, BookFactory
from recommendations import build
from recommendations.models import Recommendation, RecommendationRun, SimilarBook
from tracking.tests.factories import UserBookFactory

pytestmark = pytest.mark.django_db

THEMES = {
    "Fantasy": "dragons magic kingdom quest sword wizard",
    "Romance": "romance love wedding kiss heart summer",
}


@pytest.fixture
def catalog():
    books = {}
    for genre, words in THEMES.items():
        books[genre] = [
            BookFactory(
                title=f"{genre} {n}",
                description=f"{words} story{n} chapter{n % 2}",
                genres=[genre],
                authors=[AuthorFactory(name=f"{genre} Author {n}")],
            )
            for n in range(6)
        ]
    return books


def test_snapshot_reads_books_shelves_and_first_authors(catalog):
    reader = UserBookFactory(book=catalog["Fantasy"][0], status="finished", rating=5)
    snapshot = build.read_snapshot()
    assert len(snapshot.books) == 12
    item = snapshot.shelves[reader.user_id][0]
    assert (item.book_id, item.rating, item.key) == (
        catalog["Fantasy"][0].id,
        5,
        ("fantasy 0", "fantasy author 0"),
    )


def test_books_without_an_author_never_share_a_key():
    a, b = BookFactory(title="Untitled"), BookFactory(title="Untitled")
    keys = {x.id: x.key for x in build.read_snapshot().books}
    assert keys[a.id] != keys[b.id]


def test_build_writes_a_finished_run_and_replaces_the_old_one(catalog):
    entry = UserBookFactory(book=catalog["Fantasy"][0], status="finished", rating=5)
    first = build.write(build.compute(build.read_snapshot()), started_at=_now())
    second = build.write(build.compute(build.read_snapshot()), started_at=_now())

    assert RecommendationRun.latest_finished() == second.run
    assert not RecommendationRun.objects.filter(pk=first.run.pk).exists()
    assert second.old_runs_deleted == 1
    picks = Recommendation.objects.filter(run=second.run, user=entry.user).order_by("rank")
    assert picks.count() == second.picks > 0
    assert picks[0].book.genres == ["Fantasy"] and picks[0].because_of_id == entry.book_id
    assert not picks.filter(book=entry.book).exists()
    assert SimilarBook.objects.filter(run=second.run).count() == second.neighbour_rows
    assert SimilarBook.objects.filter(run=first.run).count() == 0


def test_build_command_prints_counts_and_releases_the_connection(catalog, capsys, monkeypatch):
    UserBookFactory(book=catalog["Romance"][0], status="finished", rating=4)
    released = []
    monkeypatch.setattr(
        "recommendations.management.commands.build_recommendations.release_connection",
        lambda: released.append(True),
    )
    call_command("build_recommendations")
    out = capsys.readouterr().out
    assert out.startswith("Database: ") and released == [True]
    assert "Books with text (scored):       12" in out
    assert "Readers with picks:             1" in out
    assert "Series boost (0.1): 0 books boosted" in out  # no series in this catalog


def test_profiles_report_holdout_is_counts_only_and_read_only(catalog, capsys):
    reader = UserBookFactory(book=catalog["Fantasy"][0], status="finished", rating=5).user
    for b in catalog["Fantasy"][1:] + catalog["Romance"][:5]:
        UserBookFactory(user=reader, book=b, status="finished", rating=5)
    # Test-only: run the deferred foreign-key checks now. The report makes this test's
    # transaction read-only, and they'd otherwise run (and fail) at teardown.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    call_command("recommendation_profiles_report", "--seeds", "3")
    out = capsys.readouterr().out
    assert out.startswith("Database: ")
    assert "Reader 1: 11 books at 4+ stars; 2 hidden per seed" in out
    assert "hits in top 20:" in out and "random picks" in out
    assert "Fantasy 1" not in out  # no titles without --profiles / --mine
    with connection.cursor() as cursor:  # the session was reset afterwards
        cursor.execute("SHOW default_transaction_read_only")
        assert cursor.fetchone()[0] == "off"


def _now():
    from django.utils import timezone

    return timezone.now()


def test_profiles_report_lists_miss_reasons_and_rules_off(catalog, capsys):
    reader = UserBookFactory(book=catalog["Fantasy"][0], status="finished", rating=5).user
    for b in catalog["Fantasy"][1:] + catalog["Romance"][:5]:
        UserBookFactory(user=reader, book=b, status="finished", rating=5)
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # see the test above
    call_command(
        "recommendation_profiles_report",
        "--seeds",
        "2",
        "--no-next-in-series",
        "--no-picture-books",
    )
    out = capsys.readouterr().out
    assert "Rules off: next-in-series, picture-books" in out
    assert "why targets missed the top 50" in out
    assert "series boost 0.1:" in out and "hits it added: top 20 +0, top 50 +0" in out

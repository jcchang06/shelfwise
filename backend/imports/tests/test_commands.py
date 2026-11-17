from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command

from catalog.tests.factories import AuthorFactory, BookFactory
from imports import processing
from imports.matching import MatchPausedError
from imports.models import GoodreadsImport
from imports.tasks import run_import_task

from .helpers import make_import, make_row

pytestmark = pytest.mark.django_db

Status = GoodreadsImport.Status


@pytest.fixture
def matchable():
    author = AuthorFactory(name="Mara Vell")
    for n in range(1, 4):
        BookFactory(title=f"Synthetic Book {n}", authors=[author], isbn_13="")


def run(name, *args) -> str:
    out = StringIO()
    call_command(name, *args, stdout=out)
    return out.getvalue()


def test_run_import_finishes(matchable):
    imp = make_import()
    for n in range(1, 4):
        make_row(imp, n)
    out = run("run_import", str(imp.pk))
    assert f"Import {imp.pk}: done, 3/3 rows" in out
    imp.refresh_from_db()
    assert imp.status == Status.DONE


def test_run_import_reports_a_pause(matchable, monkeypatch):
    imp = make_import()
    make_row(imp, 1)
    monkeypatch.setattr(
        processing, "match_row", lambda *a: (_ for _ in ()).throw(MatchPausedError("budget gone"))
    )
    out = run("run_import", str(imp.pk))
    assert "Paused: budget gone" in out


def test_run_import_unknown_id():
    with pytest.raises(CommandError, match="No import with id 999"):
        run("run_import", "999")


def test_run_pending_imports_handles_every_unfinished_import(matchable):
    pending = make_import()
    make_row(pending, 1)
    paused = make_import(status=Status.PAUSED)
    make_row(paused, 1)
    done = make_import(status=Status.DONE)

    out = run("run_pending_imports")

    for imp in (pending, paused):
        imp.refresh_from_db()
        assert imp.status == Status.DONE
    assert f"Import {done.pk}" not in out


def test_run_pending_imports_stops_when_the_budget_is_gone(matchable, monkeypatch):
    first, second = make_import(), make_import()
    make_row(first, 1)
    make_row(second, 1)
    monkeypatch.setattr(
        processing, "match_row", lambda *a: (_ for _ in ()).throw(MatchPausedError("gone"))
    )
    out = run("run_pending_imports")
    assert "Google budget used up for today; stopping." in out
    second.refresh_from_db()
    assert second.status == Status.PENDING  # not attempted: it would pause too


def test_run_pending_imports_skips_a_busy_import(matchable):
    imp = make_import()
    make_row(imp, 1)
    cache.add(processing._lock_key(imp.pk), "page", timeout=60)
    assert "busy elsewhere, skipped" in run("run_pending_imports")


def test_run_pending_imports_with_nothing_to_do():
    assert "No unfinished imports." in run("run_pending_imports")


def test_celery_task_runs_to_completion(matchable):
    imp = make_import()
    make_row(imp, 1)
    assert run_import_task.run(imp.pk) == Status.DONE  # .run: the task body, no broker

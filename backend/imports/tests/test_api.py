"""Import endpoints: upload, list, detail, process (I-2)."""

from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.tests.factories import UserFactory
from catalog.tests.factories import AuthorFactory, BookFactory
from imports import processing
from imports.models import GoodreadsImport, ImportRow

from .helpers import make_import, make_row

pytestmark = pytest.mark.django_db

SAMPLE = (Path(__file__).parent / "fixtures" / "synthetic_goodreads.csv").read_bytes()
IMPORTS = reverse("imports:import-list")


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def client(api_client, user):
    api_client.force_authenticate(user)
    return api_client


def upload(client, data: bytes = SAMPLE, name="goodreads_library_export.csv"):
    return client.post(
        IMPORTS, {"file": SimpleUploadedFile(name, data, "text/csv")}, format="multipart"
    )


class TestUpload:
    def test_creates_an_import(self, client, user):
        response = upload(client)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending" and body["total_rows"] == 12
        assert body["failed_count"] == 2 and body["placeholder_dnf_count"] == 0
        assert GoodreadsImport.objects.get().user == user

    def test_bad_file_is_a_field_error_and_saves_nothing(self, client):
        response = upload(client, b"Title,Author\nDune,Frank Herbert\n")
        assert response.status_code == 400
        assert "doesn't look like a Goodreads export" in response.json()["file"][0]
        assert not GoodreadsImport.objects.exists()

    def test_no_file(self, client):
        response = client.post(IMPORTS, {}, format="multipart")
        assert (
            response.status_code == 400
            and "Choose your Goodreads export" in response.json()["file"][0]
        )

    def test_too_large(self, client, settings):
        settings.IMPORT_MAX_FILE_BYTES = 100
        response = upload(client, b"x" * 70_000)
        assert response.status_code == 400 and "too large" in response.json()["file"][0]

    def test_uploads_are_kept_in_memory_only(self, settings):
        # Django's default writes uploads over 2.5 MB to a temp file; we must never do that.
        assert settings.FILE_UPLOAD_HANDLERS == [
            "django.core.files.uploadhandler.MemoryFileUploadHandler"
        ]
        assert settings.FILE_UPLOAD_MAX_MEMORY_SIZE >= settings.IMPORT_MAX_FILE_BYTES

    def test_requires_login(self, api_client):
        assert api_client.post(IMPORTS, {}, format="multipart").status_code == 401

    def test_celery_handoff_only_when_enabled(self, client, settings, monkeypatch):
        settings.IMPORTS_USE_CELERY = True
        sent = []
        from imports import tasks

        monkeypatch.setattr(tasks.run_import_task, "delay", lambda pk: sent.append(pk))
        upload(client)
        assert sent == [GoodreadsImport.objects.get().pk]


class TestReadAndProcess:
    def test_list_and_detail_are_mine_only(self, client, user):
        mine = make_import(user)
        theirs = make_import()
        ids = [i["id"] for i in client.get(IMPORTS).json()["results"]]
        assert ids == [mine.id]
        assert client.get(reverse("imports:import-detail", args=[theirs.pk])).status_code == 404
        assert client.post(reverse("imports:import-process", args=[theirs.pk])).status_code == 404

    def test_process_runs_a_batch_and_returns_progress(self, client, user):
        author = AuthorFactory(name="Mara Vell")
        BookFactory(title="Synthetic Book 1", authors=[author], isbn_13="")
        imp = make_import(user)
        make_row(imp, 1)
        response = client.post(reverse("imports:import-process", args=[imp.pk]))
        assert response.status_code == 200
        body = response.json()
        assert (body["status"], body["processed_rows"], body["created_count"]) == ("done", 1, 1)

    def test_process_while_busy_is_409(self, client, user):
        imp = make_import(user)
        cache.add(processing._lock_key(imp.pk), "nightly", timeout=60)
        response = client.post(reverse("imports:import-process", args=[imp.pk]))
        assert (
            response.status_code == 409 and "already being processed" in response.json()["detail"]
        )

    def test_detail_counts_placeholder_dnfs(self, client, user):
        imp = make_import(user)
        make_row(imp, 1, status="dnf")
        BookFactory(title="Synthetic Book 1", authors=[AuthorFactory(name="Mara Vell")], isbn_13="")
        client.post(reverse("imports:import-process", args=[imp.pk]))
        body = client.get(reverse("imports:import-detail", args=[imp.pk])).json()
        assert body["placeholder_dnf_count"] == 1

    def test_upload_then_process_end_to_end_without_network(self, client, user, monkeypatch):
        """The synthetic export through the API; matching is stubbed to "unmatched" so no
        Book API is called (matching itself is covered in test_matching.py)."""
        from imports.matching import Match

        monkeypatch.setattr(processing, "prefetch_isbns", lambda rows: {})
        monkeypatch.setattr(processing, "match_row", lambda row, p: Match(None, note="stub"))
        import_id = upload(client).json()["id"]
        body = client.post(reverse("imports:import-process", args=[import_id])).json()
        assert body["status"] == "done"
        assert body["unmatched_count"] == 10 and body["failed_count"] == 2
        assert ImportRow.objects.filter(state="unmatched").count() == 10

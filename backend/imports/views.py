"""Goodreads import endpoints (I-2). Every queryset is filtered to request.user."""

from django.conf import settings
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from catalog.models import Book
from catalog.services.catalog import get_or_create_book
from catalog.services.types import BookNotFoundError, BookSourceError
from catalog.views import BookSourceUnavailable

from .apply import placeholder_dnf_count
from .csv_parser import ImportFileError
from .models import GoodreadsImport, ImportRow
from .processing import ImportBusyError, process_import_batch
from .resolution import RowNotResolvableError, dismiss_row, resolve_row
from .serializers import GoodreadsImportSerializer, ImportRowSerializer, ResolveRowSerializer
from .services import create_import


def _data(request: Request, goodreads_import: GoodreadsImport) -> dict:
    goodreads_import.placeholder_dnf_count = placeholder_dnf_count(request.user)
    return GoodreadsImportSerializer(goodreads_import).data


class ImportListCreateView(generics.ListAPIView):
    """GET /api/imports/ — your imports, newest first.
    POST /api/imports/ (multipart, field "file") — upload a Goodreads export."""

    serializer_class = GoodreadsImportSerializer
    parser_classes = [MultiPartParser]

    def get_queryset(self):
        return GoodreadsImport.objects.filter(user=self.request.user)

    def list(self, request: Request, *args, **kwargs) -> Response:
        response = super().list(request, *args, **kwargs)
        count = placeholder_dnf_count(request.user)
        for item in response.data["results"]:
            item["placeholder_dnf_count"] = count
        return response

    def post(self, request: Request) -> Response:
        # Check the declared size first: uploads over the limit are not kept in memory (see
        # FILE_UPLOAD_HANDLERS), so they'd otherwise look like "no file". The multipart
        # overhead is small; 64 KB of slack covers it.
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
        if declared > settings.IMPORT_MAX_FILE_BYTES + 64 * 1024:
            limit_mb = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
            raise serializers.ValidationError(
                {"file": [f"That file is too large. The limit is {limit_mb:g} MB."]}
            )
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError(
                {"file": ["Choose your Goodreads export (a .csv file)."]}
            )
        if upload.size > settings.IMPORT_MAX_FILE_BYTES:
            limit_mb = settings.IMPORT_MAX_FILE_BYTES / (1024 * 1024)
            raise serializers.ValidationError(
                {"file": [f"That file is too large. The limit is {limit_mb:g} MB."]}
            )
        try:
            # Read into memory and parse; the upload is never saved anywhere (PRD privacy).
            goodreads_import = create_import(request.user, upload.read())
        except ImportFileError as exc:
            raise serializers.ValidationError({"file": [str(exc)]}) from exc

        if settings.IMPORTS_USE_CELERY:  # local Docker only
            from .tasks import run_import_task  # Celery is a dev-only dependency

            run_import_task.delay(goodreads_import.pk)
        return Response(_data(request, goodreads_import), status=status.HTTP_201_CREATED)


class ImportDetailView(generics.RetrieveAPIView):
    """GET /api/imports/{id}/ — progress and counts."""

    serializer_class = GoodreadsImportSerializer

    def get_queryset(self):
        return GoodreadsImport.objects.filter(user=self.request.user)

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        return Response(_data(request, self.get_object()))


class ImportProcessView(generics.GenericAPIView):
    """POST /api/imports/{id}/process/ — run one time-bounded batch (~20s), return progress.

    The import page calls this repeatedly while it's open; if the page closes, the nightly
    job finishes the rest. 409 if another batch (e.g. the nightly job) is running."""

    def get_queryset(self):
        return GoodreadsImport.objects.filter(user=self.request.user)

    def post(self, request: Request, pk: int) -> Response:
        if not self.get_queryset().filter(pk=pk).exists():
            raise NotFound()
        try:
            goodreads_import = process_import_batch(pk)
        except ImportBusyError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(_data(request, goodreads_import))


class ImportRowListView(generics.ListAPIView):
    """GET /api/imports/{id}/rows/?state=unmatched|failed — rows needing attention (I-4)."""

    serializer_class = ImportRowSerializer
    VISIBLE = (ImportRow.State.UNMATCHED, ImportRow.State.FAILED)

    def get_queryset(self):
        goodreads_import = _own_import(self.request, self.kwargs["pk"])
        state = self.request.query_params.get("state", ImportRow.State.UNMATCHED)
        if state not in self.VISIBLE:
            raise serializers.ValidationError({"state": ["Must be unmatched or failed."]})
        return goodreads_import.rows.filter(state=state).order_by("row_number")


def _own_import(request: Request, pk: int) -> GoodreadsImport:
    goodreads_import = GoodreadsImport.objects.filter(user=request.user, pk=pk).first()
    if goodreads_import is None:
        raise NotFound()
    return goodreads_import


def _row_result(request: Request, goodreads_import: GoodreadsImport, row: ImportRow) -> dict:
    return {
        "row": {"id": row.id, "state": row.state, "note": row.note},
        "book_id": row.book_id,
        "user_book_id": row.user_book_id,
        "import": _data(request, goodreads_import),
    }


class ResolveRowView(generics.GenericAPIView):
    """POST /api/imports/{id}/rows/{row_id}/resolve/ {book_id} or {source, source_id}.

    Matches an unmatched row by hand and adds it to the shelf with the row's Goodreads
    status, rating, dates and review. Like adding from search, a {source, source_id} may
    call the book API (user-initiated)."""

    def post(self, request: Request, pk: int, row_id: int) -> Response:
        goodreads_import = _own_import(request, pk)
        body = ResolveRowSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        book = _resolve_book(body.validated_data)
        try:
            row = resolve_row(goodreads_import, row_id, book)
        except ImportRow.DoesNotExist as exc:
            raise NotFound() from exc
        except RowNotResolvableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(_row_result(request, goodreads_import, row))


class DismissRowView(generics.GenericAPIView):
    """POST /api/imports/{id}/rows/{row_id}/dismiss/ — skip an unmatched row."""

    def post(self, request: Request, pk: int, row_id: int) -> Response:
        goodreads_import = _own_import(request, pk)
        try:
            row = dismiss_row(goodreads_import, row_id)
        except ImportRow.DoesNotExist as exc:
            raise NotFound() from exc
        except RowNotResolvableError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(_row_result(request, goodreads_import, row))


def _resolve_book(data: dict) -> Book:
    if "book_id" in data:
        book = Book.objects.filter(pk=data["book_id"]).first()
        if book is None:
            raise serializers.ValidationError({"book_id": ["No catalog book with this ID."]})
        return book
    try:
        book, _ = get_or_create_book(data["source"], data["source_id"])
    except BookNotFoundError as exc:
        raise NotFound(f"No {data['source'].value} book with ID {data['source_id']}.") from exc
    except BookSourceError as exc:
        raise BookSourceUnavailable(
            "Couldn't reach the book source to match this row. Please try again shortly."
        ) from exc
    return book

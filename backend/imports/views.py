"""Goodreads import endpoints (I-2). Every queryset is filtered to request.user."""

from django.conf import settings
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from .apply import placeholder_dnf_count
from .csv_parser import ImportFileError
from .models import GoodreadsImport
from .processing import ImportBusyError, process_import_batch
from .serializers import GoodreadsImportSerializer
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

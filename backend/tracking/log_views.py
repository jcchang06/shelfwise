"""Page log endpoints (T-3). Every queryset here is filtered to request.user."""

from rest_framework import generics, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from catalog.models import Book

from .models import ReadingLog, UserBook
from .reading_logs import LogRuleError, log_pages, pages_logged, update_log
from .serializers import (
    LogCreateSerializer,
    LogShelfEntrySerializer,
    LogUpdateSerializer,
    ReadingLogSerializer,
)


def _rule_error(exc: LogRuleError) -> Response:
    """400 with {field: [message]} like DRF's own errors, plus conflict_id when a day is taken.

    Built as a Response rather than a ValidationError because DRF stringifies every value
    in a ValidationError, and conflict_id must stay an integer to match log ids.
    """
    detail: dict = {field: [message] for field, message in exc.errors.items()}
    if exc.conflict_id is not None:
        detail["conflict_id"] = exc.conflict_id
    return Response(detail, status=status.HTTP_400_BAD_REQUEST)


def _with_shelf_entry(log: ReadingLog, user_book: UserBook | None) -> dict:
    data = dict(ReadingLogSerializer(log).data)
    data["shelf_entry"] = (
        LogShelfEntrySerializer(
            {
                "id": user_book.pk,
                "status": user_book.status,
                "started_at": user_book.started_at,
                "pages_logged": pages_logged(user_book),
            }
        ).data
        if user_book
        else None
    )
    return data


class LogListCreateView(generics.ListCreateAPIView):
    """GET /api/logs/?book=&from=&to=  ·  POST /api/logs/ {book_id, pages_read, log_date?}"""

    serializer_class = ReadingLogSerializer

    def get_queryset(self):
        queryset = ReadingLog.objects.filter(user=self.request.user).order_by("-log_date", "-id")
        params = self.request.query_params

        book = params.get("book")
        if book:
            if not book.isdigit():
                raise serializers.ValidationError({"book": "Must be a book ID."})
            queryset = queryset.filter(book_id=int(book))

        date_field = serializers.DateField()
        for param, lookup in (("from", "log_date__gte"), ("to", "log_date__lte")):
            if params.get(param):
                try:
                    value = date_field.to_internal_value(params[param])
                except serializers.ValidationError as exc:
                    raise serializers.ValidationError({param: "Use YYYY-MM-DD."}) from exc
                queryset = queryset.filter(**{lookup: value})
        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        body = LogCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        book = Book.objects.filter(pk=data["book_id"]).first()
        if book is None:
            raise serializers.ValidationError({"book_id": ["No catalog book with this ID."]})
        try:
            log, created, user_book = log_pages(
                request.user, book, data["pages_read"], data.get("log_date")
            )
        except LogRuleError as exc:
            return _rule_error(exc)

        return Response(
            _with_shelf_entry(log, user_book),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class LogDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE /api/logs/{id}/. PATCH sets the day's total; no PUT."""

    serializer_class = ReadingLogSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return ReadingLog.objects.filter(user=self.request.user)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        log = self.get_object()
        body = LogUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            log, user_book = update_log(log, dict(body.validated_data))
        except LogRuleError as exc:
            return _rule_error(exc)
        return Response(_with_shelf_entry(log, user_book))

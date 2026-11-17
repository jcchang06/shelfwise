"""Shelf endpoints (T-2, T-4, T-6). Every queryset here is filtered to request.user."""

import datetime as dt

from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    DateField,
    IntegerField,
    OuterRef,
    Prefetch,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from rest_framework import generics, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from catalog.models import Book, BookAuthor
from catalog.services.catalog import get_or_create_book
from catalog.services.types import BookNotFoundError, BookSourceError
from catalog.views import BookSourceUnavailable

from .models import ReadingLog, UserBook
from .serializers import AddToShelfSerializer, ShelfChangesSerializer, UserBookSerializer
from .services import ShelfRuleError, apply_shelf_changes

ORDERINGS = {
    "-updated_at": ("-updated_at", "-id"),
    "title": ("book__title", "id"),
    "-finished_at": ("-finished_at", "-id"),
    "-created_at": ("-created_at", "-id"),
}


def shelf_for(user):
    """The user's shelf with everything the serializer needs, in a constant number of queries."""
    logs = ReadingLog.objects.filter(user=OuterRef("user"), book=OuterRef("book")).values("book")
    # pages_logged covers the current read only (see services.current_read_logs);
    # reading_log_count covers every log, since removing the book deletes them all.
    current_read = logs.filter(
        log_date__gte=Coalesce(OuterRef("started_at"), Value(dt.date.min), output_field=DateField())
    )
    return (
        UserBook.objects.filter(user=user)
        .select_related("book")
        .prefetch_related(
            Prefetch(
                "book__book_authors",
                queryset=BookAuthor.objects.select_related("author").order_by("position"),
            )
        )
        .annotate(
            pages_logged=Coalesce(
                Subquery(current_read.annotate(total=Sum("pages_read")).values("total")),
                Value(0),
                output_field=IntegerField(),
            ),
            reading_log_count=Coalesce(
                Subquery(logs.annotate(n=Count("id")).values("n")),
                Value(0),
                output_field=IntegerField(),
            ),
        )
    )


def _apply(user_book: UserBook, changes: dict) -> None:
    try:
        apply_shelf_changes(user_book, changes)
    except ShelfRuleError as exc:
        # Same shape as DRF's own field errors: {field: [message]}.
        raise serializers.ValidationError({f: [m] for f, m in exc.errors.items()}) from exc


class ShelfListCreateView(generics.ListCreateAPIView):
    """GET /api/shelf/?status=&book=&ordering=  ·  POST /api/shelf/"""

    serializer_class = UserBookSerializer

    def get_queryset(self):
        params = self.request.query_params
        queryset = shelf_for(self.request.user)

        status_filter = params.get("status")
        if status_filter:
            if status_filter not in UserBook.Status.values:
                raise serializers.ValidationError({"status": "Unknown status."})
            queryset = queryset.filter(status=status_filter)

        book = params.get("book")
        if book:
            if not book.isdigit():
                raise serializers.ValidationError({"book": "Must be a book ID."})
            queryset = queryset.filter(book_id=int(book))

        ordering = params.get("ordering", "-updated_at")
        if ordering not in ORDERINGS:
            raise serializers.ValidationError(
                {"ordering": f"Must be one of: {', '.join(ORDERINGS)}."}
            )
        return queryset.order_by(*ORDERINGS[ordering])

    def create(self, request: Request, *args, **kwargs) -> Response:
        body = AddToShelfSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        book_ref, changes = body.split()

        book = self._resolve_book(book_ref)
        existing = UserBook.objects.filter(user=request.user, book=book).first()
        if existing:
            return self._already_on_shelf(existing.pk)

        user_book = UserBook(user=request.user, book=book)
        _apply(user_book, changes)
        try:
            with transaction.atomic():
                user_book.save()
        except IntegrityError:  # added by a concurrent request since the check above
            existing = UserBook.objects.get(user=request.user, book=book)
            return self._already_on_shelf(existing.pk)

        data = UserBookSerializer(shelf_for(request.user).get(pk=user_book.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _resolve_book(book_ref: dict) -> Book:
        if "book_id" in book_ref:
            book = Book.objects.filter(pk=book_ref["book_id"]).first()
            if book is None:
                raise serializers.ValidationError({"book_id": "No catalog book with this ID."})
            return book
        source, source_id = book_ref["source"], book_ref["source_id"]
        try:
            book, _ = get_or_create_book(source, source_id)
        except BookNotFoundError as exc:
            raise NotFound(f"No {source.value} book with ID {source_id}.") from exc
        except BookSourceError as exc:
            raise BookSourceUnavailable(
                "Couldn't reach the book source to add this book. Please try again shortly."
            ) from exc
        return book

    @staticmethod
    def _already_on_shelf(user_book_id: int) -> Response:
        return Response(
            {"detail": "This book is already on your shelf.", "id": user_book_id},
            status=status.HTTP_409_CONFLICT,
        )


class ShelfDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET / PATCH / DELETE /api/shelf/{id}/. Another user's entry is a 404."""

    serializer_class = UserBookSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]  # no PUT

    def get_queryset(self):
        return shelf_for(self.request.user)

    def partial_update(self, request: Request, *args, **kwargs) -> Response:
        user_book = self.get_object()
        body = ShelfChangesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        _apply(user_book, dict(body.validated_data))
        user_book.save()
        return Response(UserBookSerializer(self.get_queryset().get(pk=user_book.pk)).data)

    def perform_destroy(self, instance: UserBook) -> None:
        # Removing a book also removes this user's logs for it (confirmed in the UI first,
        # using reading_log_count). A DNF, by contrast, keeps them.
        with transaction.atomic():
            ReadingLog.objects.filter(user=instance.user, book=instance.book).delete()
            instance.delete()

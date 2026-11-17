"""Catalog endpoints (C-1, C-2). The catalog is shared, so these aren't filtered by user,
but they all require login (the default permission)."""

from django.db.models import Prefetch
from rest_framework import generics, status
from rest_framework.exceptions import APIException, NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tracking.services import shelf_entries_for  # per-user; only read to label results

from .models import Author, Book, BookAuthor
from .serializers import (
    PAGE_SIZES,
    BookSerializer,
    SaveBookSerializer,
    SearchQuerySerializer,
    SearchResultSerializer,
    search_result_data,
)
from .services.authors import (
    author_ids_for,
    author_works_for,
    group_by_series,
    resolve_author_key,
)
from .services.catalog import catalog_ids_for, get_or_create_book
from .services.search import search_books
from .services.types import BookNotFoundError, BookSearchUnavailableError, BookSourceError


class BookSourceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Book search is temporarily unavailable. Please try again in a few minutes."
    default_code = "book_source_unavailable"


def books_with_authors():
    return Book.objects.prefetch_related(
        Prefetch(
            "book_authors",
            queryset=BookAuthor.objects.select_related("author").order_by("position"),
        )
    )


class BookSearchView(APIView):
    """GET /api/books/search/?q=...&page=1 (C-1).

    Not a DB queryset, so it uses a simple page number instead of DRF pagination:
    `next_page` is null when this page wasn't full.
    """

    throttle_scope = "book_search"

    def get(self, request: Request) -> Response:
        params = SearchQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        query, page = params.validated_data["q"], params.validated_data["page"]

        try:
            found = search_books(query, page)
        except BookSearchUnavailableError as exc:
            raise BookSourceUnavailable() from exc

        # The source results above may come from the shared 24h cache. book_id and shelf
        # depend on the current catalog and on who is asking, so they are computed here,
        # per request, after the cache read, and never stored in the cache.
        ids = catalog_ids_for(found.results)
        author_ids = author_ids_for(found.results)
        shelves = shelf_entries_for(request.user, ids)
        results = [
            search_result_data(result, book_id, shelves.get(book_id), authors)
            for result, book_id, authors in zip(found.results, ids, author_ids, strict=True)
        ]
        full_page = len(results) >= PAGE_SIZES[found.source]
        return Response(
            {
                "source": found.source.value,  # the UI shows attribution for this source
                "page": page,
                "next_page": page + 1 if full_page else None,
                "results": SearchResultSerializer(results, many=True).data,
            }
        )


class BookListCreateView(APIView):
    """POST /api/books/ {source, source_id} saves a search result to the catalog (C-2).

    The server fetches the metadata itself rather than trusting what the client sends.
    Returns 201 for a new book, 200 if it was already in the catalog.
    """

    def post(self, request: Request) -> Response:
        serializer = SaveBookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source, source_id = (
            serializer.validated_data["source"],
            serializer.validated_data["source_id"],
        )

        try:
            book, created = get_or_create_book(source, source_id)
        except BookNotFoundError as exc:
            raise NotFound(f"No {source.value} book with ID {source_id}.") from exc
        except BookSourceError as exc:
            raise BookSourceUnavailable(
                "Couldn't reach the book source to save this book. Please try again shortly."
            ) from exc

        book = books_with_authors().get(pk=book.pk)
        return Response(
            BookSerializer(book).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class BookDetailView(generics.RetrieveAPIView):
    """GET /api/books/{id}/ — one catalog book."""

    serializer_class = BookSerializer

    def get_queryset(self):
        return books_with_authors()


class AuthorDetailView(APIView):
    """GET /api/authors/{id}/ (C-5): the author, their works grouped by series, and the
    caller's shelf status on each.

    Looks the author up in Open Library when it isn't cached (up to a few throttled
    requests on the first view, then a day's cache), the same user-initiated exception as
    search; hence the search throttle. If Open Library can't be reached, the author's
    catalog books are still returned, with `works_unavailable: true`.
    """

    throttle_scope = "book_search"

    def get(self, request: Request, pk: int) -> Response:
        author = Author.objects.filter(pk=pk).first()
        if author is None:
            raise NotFound("No author with this ID.")
        unavailable = False
        try:
            key = resolve_author_key(author)
            items = author_works_for(author, key)
        except BookSourceError:
            unavailable = True
            key = author.open_library_key
            items = author_works_for(author, None)
        shelves = shelf_entries_for(request.user, [i.book_id for i in items])
        return Response(
            {
                "id": author.pk,
                "name": author.name,
                "open_library_key": key,
                "open_library_url": f"https://openlibrary.org/authors/{key}" if key else None,
                "works_unavailable": unavailable,
                "groups": group_by_series(items, shelves),
            }
        )

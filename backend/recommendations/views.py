"""Recommendation endpoints (R-2, R-3). They only read what the nightly build wrote: the
latest finished run (PRD: never computed per request). Shelf status is computed per
request, since the reader may have shelved a pick since the run."""

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Book, BookAuthor
from tracking.services import shelf_entries_for

from .models import Recommendation, RecommendationRun, SimilarBook
from .serializers import SuggestedBookSerializer

MAX_SIMILAR = 10


def _with_authors(field: str) -> Prefetch:
    return Prefetch(
        f"{field}__book_authors",
        queryset=BookAuthor.objects.select_related("author").order_by("position"),
    )


def _book(book: Book, shelves: dict) -> dict:
    return {**SuggestedBookSerializer(book).data, "shelf": shelves.get(book.pk)}


class RecommendationsView(APIView):
    """GET /api/recommendations/ -> {computed_at, results: [{rank, book, because_of}]}.

    computed_at is null before the first nightly run. With a run but no results, the
    reader has no rated or finished books with text yet.
    """

    def get(self, request: Request) -> Response:
        run = RecommendationRun.latest_finished()
        if run is None:
            return Response({"computed_at": None, "results": []})
        picks = list(
            Recommendation.objects.filter(run=run, user=request.user)
            .select_related("book", "because_of")
            .prefetch_related(_with_authors("book"))
            .order_by("rank")
        )
        shelves = shelf_entries_for(request.user, [p.book_id for p in picks])
        return Response(
            {
                "computed_at": run.finished_at,
                "results": [
                    {
                        "rank": p.rank,
                        "book": _book(p.book, shelves),
                        "because_of": (
                            {"id": p.because_of.pk, "title": p.because_of.title}
                            if p.because_of
                            else None
                        ),
                    }
                    for p in picks
                ],
            }
        )


class SimilarBooksView(APIView):
    """GET /api/books/{id}/similar/?limit=6 (R-3): the book's most similar books, best first,
    each with the caller's shelf status. Empty before the first nightly run."""

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Book, pk=pk)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 6)), MAX_SIMILAR))
        except ValueError:
            limit = 6
        run = RecommendationRun.latest_finished()
        rows = (
            list(
                SimilarBook.objects.filter(run=run, book_id=pk)
                .select_related("similar")
                .prefetch_related(_with_authors("similar"))
                .order_by("rank")[:limit]
            )
            if run
            else []
        )
        shelves = shelf_entries_for(request.user, [r.similar_id for r in rows])
        return Response({"results": [_book(r.similar, shelves) for r in rows]})

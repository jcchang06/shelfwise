"""Reading inputs for, and writing results of, the nightly recommendation build (R-1).

The same pattern as the seed build, for Neon: read a snapshot in one short transaction,
release the connection, compute in memory (engine.py), then write the new run in short
batches. Readers only see a run once it's marked finished; older runs are then deleted.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from catalog.models import Book, BookAuthor
from catalog.services import normalize
from tracking.models import UserBook

from .engine import BookText, Model, Params, Pick, ShelfItem
from .models import Recommendation, RecommendationRun, SimilarBook

WRITE_BATCH = 2_000


@dataclass
class Snapshot:
    books: list[BookText]
    shelves: dict[int, list[ShelfItem]]  # user id -> shelf


def read_snapshot() -> Snapshot:
    """Every book (title, description, genres, first author) and every shelf entry, in one
    short transaction: two book queries and one shelf query."""
    with transaction.atomic():
        first_author: dict[int, str] = {}
        for book_id, name in BookAuthor.objects.order_by("book_id", "position", "id").values_list(
            "book_id", "author__name"
        ):
            first_author.setdefault(book_id, name)
        books = []
        for book_id, title, description, genres in Book.objects.order_by("id").values_list(
            "id", "title", "description", "genres"
        ):
            author = first_author.get(book_id, "")
            # Without an author a title alone is too weak to call two books the same one.
            key = (
                normalize.title_author_key(title, author)
                if author
                else (normalize.normalize_title(title), f"#{book_id}")
            )
            books.append(
                BookText(
                    id=book_id,
                    title=title,
                    description=description or "",
                    genres=tuple(genres or ()),
                    author=normalize.normalize_author_name(author) if author else "",
                    key=key,
                )
            )
        keys = {b.id: b.key for b in books}
        shelves: dict[int, list[ShelfItem]] = defaultdict(list)
        for user_id, book_id, status, rating, reason in UserBook.objects.values_list(
            "user_id", "book_id", "status", "rating", "dnf_reason"
        ):
            shelves[user_id].append(ShelfItem(book_id, status, rating, reason, keys[book_id]))
    return Snapshot(books, dict(shelves))


@dataclass
class Results:
    model: Model
    picks: dict[int, list[Pick]]
    neighbours: dict[int, list[tuple[int, float]]]
    seconds: float


DEFAULT_PARAMS = Params()


def compute(snapshot: Snapshot, params: Params = DEFAULT_PARAMS) -> Results:
    started = time.perf_counter()
    model = Model(snapshot.books, params)
    weights = settings.DNF_REASON_WEIGHTS
    picks = {user: model.picks(shelf, weights) for user, shelf in snapshot.shelves.items()}
    neighbours = model.neighbours()
    return Results(model, picks, neighbours, time.perf_counter() - started)


@dataclass
class WriteReport:
    run: RecommendationRun
    picks: int = 0
    users_with_picks: int = 0
    neighbour_rows: int = 0
    old_runs_deleted: int = 0
    seconds: float = 0
    users_without_picks: list[int] = field(default_factory=list)


def _in_batches(model_class, rows) -> int:
    for start in range(0, len(rows), WRITE_BATCH):
        with transaction.atomic():
            model_class.objects.bulk_create(rows[start : start + WRITE_BATCH])
    return len(rows)


def write(results: Results, started_at) -> WriteReport:
    began = time.perf_counter()
    run = RecommendationRun.objects.create(
        started_at=started_at,
        books=len(results.model.books),
        vocabulary=results.model.vocabulary,
        seconds=results.seconds,
    )
    report = WriteReport(run=run)
    pick_rows = [
        Recommendation(
            run=run,
            user_id=user,
            book_id=pick.book_id,
            rank=rank,
            score=pick.score,
            because_of_id=pick.because_of,
        )
        for user, picks in results.picks.items()
        for rank, pick in enumerate(picks, start=1)
    ]
    report.picks = _in_batches(Recommendation, pick_rows)
    report.users_with_picks = sum(1 for picks in results.picks.values() if picks)
    report.users_without_picks = [u for u, picks in results.picks.items() if not picks]
    neighbour_rows = [
        SimilarBook(run=run, book_id=book, similar_id=similar, rank=rank, score=score)
        for book, similar_books in results.neighbours.items()
        for rank, (similar, score) in enumerate(similar_books, start=1)
    ]
    report.neighbour_rows = _in_batches(SimilarBook, neighbour_rows)

    with transaction.atomic():
        run.finished_at = timezone.now()
        run.save(update_fields=["finished_at"])
    # Older runs: their rows first (a plain DELETE each, no per-row cascade), then the runs.
    old = RecommendationRun.objects.exclude(pk=run.pk).values_list("pk", flat=True)
    old_ids = list(old)
    if old_ids:
        SimilarBook.objects.filter(run_id__in=old_ids).delete()
        Recommendation.objects.filter(run_id__in=old_ids).delete()
        report.old_runs_deleted = RecommendationRun.objects.filter(pk__in=old_ids).delete()[0]
    report.seconds = time.perf_counter() - began
    return report

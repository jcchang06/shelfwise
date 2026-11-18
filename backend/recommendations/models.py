"""Precomputed recommendations (R-1, R-2, R-3). Built nightly by build_recommendations;
API requests only read them (PRD: never computed per request).

Every row belongs to a RecommendationRun. A run's rows are written in batches, then the run
is marked finished; readers use the latest finished run, so they never see a half-written
set. Older runs' rows are deleted afterwards.
"""

from django.conf import settings
from django.db import models

from catalog.models import Book


class RecommendationRun(models.Model):
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)  # null: still writing
    books = models.PositiveIntegerField(default=0)  # books with text that were scored
    vocabulary = models.PositiveIntegerField(default=0)
    seconds = models.FloatField(default=0)  # compute time (not reads and writes)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Run {self.pk} ({'finished' if self.finished_at else 'writing'})"

    @classmethod
    def latest_finished(cls) -> "RecommendationRun | None":
        return cls.objects.filter(finished_at__isnull=False).order_by("-finished_at").first()


class Recommendation(models.Model):
    """One of a user's personal picks (R-2), with the liked book it's most like (R-4)."""

    run = models.ForeignKey(RecommendationRun, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()  # 1 = best
    score = models.FloatField()
    because_of = models.ForeignKey(
        Book, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["run", "user", "book"], name="unique_run_user_pick")
        ]
        indexes = [models.Index(fields=["run", "user", "rank"], name="rec_run_user_rank_idx")]

    def __str__(self) -> str:
        return f"#{self.rank} for user {self.user_id}: book {self.book_id}"


class SimilarBook(models.Model):
    """ "More like this" (R-3): a book's nearest neighbours by TF-IDF cosine similarity."""

    run = models.ForeignKey(RecommendationRun, on_delete=models.CASCADE, related_name="+")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="+")
    similar = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="+")
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()

    class Meta:
        ordering = ["rank"]
        constraints = [
            models.UniqueConstraint(fields=["run", "book", "similar"], name="unique_run_similar")
        ]
        indexes = [models.Index(fields=["run", "book", "rank"], name="similar_run_book_rank_idx")]

    def __str__(self) -> str:
        return f"Book {self.book_id} ~ {self.similar_id} (#{self.rank})"

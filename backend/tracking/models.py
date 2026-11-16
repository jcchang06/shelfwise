from django.conf import settings
from django.db import models
from django.db.models import Q

from catalog.models import Book


class UserBook(models.Model):
    """One book on one user's shelf (T-2), with rating/review (T-4) and DNF details (T-6)."""

    class Status(models.TextChoices):
        WANT_TO_READ = "want_to_read", "Want to read"
        READING = "reading", "Reading"
        FINISHED = "finished", "Finished"
        DNF = "dnf", "Did not finish"

    class DnfReason(models.TextChoices):
        WRITING_STYLE = "writing_style", "Writing style"
        PACING = "pacing", "Pacing"
        CONTENT = "content", "Content"
        NOT_MY_GENRE = "not_my_genre", "Not my genre"
        NOT_IN_THE_MOOD = "not_in_the_mood", "Not in the mood"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_books"
    )
    # PROTECT: the catalog is shared, so a book can't vanish from under someone's shelf.
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="user_books")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WANT_TO_READ)

    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    review = models.TextField(blank=True)
    # Dates, not timestamps: matches what a Goodreads export provides (Phase 2).
    started_at = models.DateField(null=True, blank=True)
    finished_at = models.DateField(null=True, blank=True)

    # DNF details describe the *current* DNF and are cleared when the book is resumed,
    # so a book you're reading again never counts as a negative signal (R-5).
    dnf_page = models.PositiveIntegerField(null=True, blank=True)
    dnf_at = models.DateField(null=True, blank=True)
    dnf_reason = models.CharField(max_length=16, choices=DnfReason.choices, blank=True)
    dnf_note = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "book"], name="unique_user_book"),
            models.CheckConstraint(
                name="user_book_rating_1_to_5",
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
            ),
            models.CheckConstraint(
                name="user_book_dnf_requires_reason",
                condition=~Q(status="dnf") | ~Q(dnf_reason=""),
            ),
        ]
        indexes = [models.Index(fields=["user", "status"], name="user_book_user_status_idx")]

    def __str__(self) -> str:
        return f"{self.user} – {self.book} ({self.status})"


class ReadingLog(models.Model):
    """Pages read on one day for one book (T-3). One row per user, book and day.

    Logs point at Book rather than UserBook so they survive a status change, including DNF.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reading_logs"
    )
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="reading_logs")
    log_date = models.DateField()
    pages_read = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-log_date"]
        constraints = [
            # Logging the same book again on the same day adds to this row (T-3 API).
            models.UniqueConstraint(
                fields=["user", "book", "log_date"], name="unique_reading_log_per_day"
            ),
            models.CheckConstraint(
                name="reading_log_pages_positive", condition=Q(pages_read__gt=0)
            ),
        ]
        indexes = [models.Index(fields=["user", "log_date"], name="reading_log_user_date_idx")]

    def __str__(self) -> str:
        return f"{self.user} – {self.book}: {self.pages_read} pages on {self.log_date}"

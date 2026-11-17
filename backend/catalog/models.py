from django.db import models
from django.db.models import Q

from .dates import DatePrecision


class Author(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    # e.g. "OL23919A". Lets later jobs dedupe authors and fetch their works (N-2).
    open_library_key = models.CharField(max_length=32, null=True, blank=True, unique=True)  # noqa: DJ001
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Book(models.Model):
    """A book in the shared catalog (C-2). Shelf state per user lives in tracking.UserBook."""

    # External IDs are nullable *and* unique: NULLs never collide in Postgres, so a book
    # can come from either source (or be entered by hand) without a placeholder value.
    # null=True on CharFields is deliberate here (DJ001): "" would collide under unique.
    google_books_id = models.CharField(max_length=32, null=True, blank=True, unique=True)  # noqa: DJ001
    open_library_key = models.CharField(max_length=32, null=True, blank=True, unique=True)  # noqa: DJ001
    # Indexed, not unique: Google Books sometimes returns two volume IDs for one ISBN.
    isbn_13 = models.CharField(max_length=13, blank=True, db_index=True)

    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    genres = models.JSONField(default=list, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    # APIs often return only "2014" or "2014-03". We store the earliest matching day plus
    # the precision, so date-range queries (N-2) stay simple and the UI can still show "2014".
    published_date = models.DateField(null=True, blank=True)
    published_date_precision = models.CharField(
        max_length=5, choices=DatePrecision.choices, blank=True
    )

    cover_url = models.URLField(max_length=500, blank=True)

    # Series columns exist from Phase 1; features using them are P2 (C-4, R-6, N-7).
    series_name = models.CharField(max_length=255, blank=True)
    # Decimal, not int, so novellas like "2.5" fit.
    series_number = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    authors = models.ManyToManyField(Author, through="BookAuthor", related_name="books")

    # When the nightly enrichment job (C-6) last looked this book up in Open Library, found
    # or not. Books still missing data are retried 30 days later, not every night.
    enrichment_checked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            # A date and its precision are set together or not at all.
            models.CheckConstraint(
                name="book_published_date_has_precision",
                condition=(
                    Q(published_date__isnull=True, published_date_precision="")
                    | (Q(published_date__isnull=False) & ~Q(published_date_precision=""))
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def published_date_display(self) -> str:
        """Publish date at the precision the source gave: "2014", "2014-03" or "2014-03-05"."""
        if self.published_date is None:
            return ""
        return {
            DatePrecision.YEAR: self.published_date.strftime("%Y"),
            DatePrecision.MONTH: self.published_date.strftime("%Y-%m"),
        }.get(self.published_date_precision, self.published_date.isoformat())


class BookAuthor(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="book_authors")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="book_authors")
    # Credit order, so the primary author displays first.
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["book", "position"]
        constraints = [
            models.UniqueConstraint(fields=["book", "author"], name="unique_book_author"),
        ]

    def __str__(self) -> str:
        return f"{self.author} – {self.book}"

"""Goodreads CSV import (Phase 2: I-1 to I-4).

- GoodreadsImport: one upload and its progress counters (I-2).
- ImportRow: one parsed CSV row with only the columns we use. The CSV itself is never
  stored (PRD privacy); matched rows are deleted when the import finishes, unmatched rows
  stay until resolved or dismissed (I-4).
- GoodreadsLink: which shelf entry a Goodreads "Book Id" became, so re-imports update
  instead of duplicating (I-3). A table rather than a field on UserBook because two
  Goodreads editions can map to the same catalog book.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from tracking.models import UserBook


class GoodreadsImport(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"  # e.g. Google budget used up; resumes the next day
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="goodreads_imports"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)

    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status"], name="goodreads_import_status_idx")]

    def __str__(self) -> str:
        return f"Import {self.pk} by {self.user} ({self.status})"


class ImportRow(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CREATED = "created", "Created"  # a new shelf entry
        UPDATED = "updated", "Updated"  # an existing linked entry, updated from Goodreads
        SKIPPED = "skipped", "Skipped"  # e.g. changed in Shelfwise since the last sync
        UNMATCHED = "unmatched", "Unmatched"  # needs a manual match (I-4)
        DISMISSED = "dismissed", "Dismissed"  # the user chose to skip it (I-4)
        FAILED = "failed", "Failed"  # unusable row (e.g. no title)

    class MatchMethod(models.TextChoices):
        CATALOG_ISBN = "catalog_isbn", "Catalog, by ISBN"
        CATALOG_TITLE = "catalog_title", "Catalog, by title and author"
        ISBN = "isbn", "Book API, by ISBN"
        TITLE_AUTHOR = "title_author", "Book API, by title and author"
        MANUAL = "manual", "Matched by hand"

    goodreads_import = models.ForeignKey(
        GoodreadsImport, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.PositiveIntegerField()  # 1-based, excluding the header
    goodreads_book_id = models.CharField(max_length=32)

    # Parsed fields (only what the import uses; private notes etc. are never kept).
    title = models.CharField(max_length=500)  # series suffix removed
    author = models.CharField(max_length=255, blank=True)
    additional_authors = models.TextField(blank=True)
    isbn_13 = models.CharField(max_length=13, blank=True)  # ISBN-10s converted
    page_count = models.PositiveIntegerField(null=True, blank=True)
    year_published = models.PositiveSmallIntegerField(null=True, blank=True)
    series_name = models.CharField(max_length=255, blank=True)
    series_number = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    status = models.CharField(max_length=16, choices=UserBook.Status.choices)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    date_read = models.DateField(null=True, blank=True)
    date_added = models.DateField(null=True, blank=True)
    review = models.TextField(blank=True)

    # Outcome.
    state = models.CharField(max_length=9, choices=State.choices, default=State.PENDING)
    match_method = models.CharField(max_length=13, choices=MatchMethod.choices, blank=True)
    note = models.TextField(blank=True)  # what we changed or why it didn't match
    book = models.ForeignKey(
        "catalog.Book", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    user_book = models.ForeignKey(
        UserBook, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["goodreads_import", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["goodreads_import", "row_number"], name="unique_import_row_number"
            ),
            models.CheckConstraint(
                name="import_row_rating_1_to_5",
                condition=Q(rating__isnull=True) | Q(rating__gte=1, rating__lte=5),
            ),
        ]
        indexes = [models.Index(fields=["goodreads_import", "state"], name="import_row_state_idx")]

    def __str__(self) -> str:
        return f"Row {self.row_number}: {self.title} ({self.state})"


class GoodreadsLink(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="goodreads_links"
    )
    goodreads_book_id = models.CharField(max_length=32)
    # Removing the book from the shelf removes the link; a later import re-creates both.
    user_book = models.ForeignKey(
        UserBook, on_delete=models.CASCADE, related_name="goodreads_links"
    )
    # When the import last wrote this entry. Re-imports only update entries whose
    # updated_at is not later than this (unchanged in Shelfwise since).
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "goodreads_book_id"], name="unique_goodreads_link_per_user"
            ),
        ]

    def __str__(self) -> str:
        return f"Goodreads {self.goodreads_book_id} -> {self.user_book_id}"

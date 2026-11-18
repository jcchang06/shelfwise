"""Re-normalize every catalog book's stored genres with normalize.normalize_genres (split
"Fiction, romance, general" into genres, drop "General" and STATS_EXCLUDED_GENRES, fix
casing, dedupe ignoring case). Run before R-1 builds TF-IDF from genres.

    python manage.py normalize_genres --dry-run   # before/after counts; no writes
    python manage.py normalize_genres --apply

Prints the database first (dbinfo). Running it again changes nothing. Output is counts.
"""

from collections import Counter

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Book
from catalog.services.normalize import normalize_genres

BATCH_SIZE = 500


def _stats(genre_lists) -> tuple[int, int, int, int]:
    """(distinct values ignoring case, tags, books with no genres, books with a joined value)"""
    distinct: set[str] = set()
    tags = empty = joined = 0
    for genres in genre_lists:
        tags += len(genres)
        empty += not genres
        joined += any("," in g or "/" in g for g in genres)
        distinct.update(g.casefold() for g in genres)
    return len(distinct), tags, empty, joined


class Command(BaseCommand):
    help = "Re-normalize stored book genres (--dry-run first, then --apply)."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Report only; no writes.")
        mode.add_argument("--apply", action="store_true", help="Write the new genres.")

    def handle(self, *args, dry_run: bool, apply: bool, **options):
        call_command("dbinfo", stdout=self.stdout)
        if not dry_run and not apply:
            raise CommandError("Run with --dry-run first, review the counts, then --apply.")

        rows = list(Book.objects.order_by("id").values_list("id", "genres"))
        before = [list(genres or []) for _, genres in rows]
        after = [list(normalize_genres(genres)) for genres in before]
        changed = [
            (book_id, new)
            for (book_id, _), old, new in zip(rows, before, after, strict=True)
            if new != old
        ]

        b_distinct, b_tags, b_empty, b_joined = _stats(before)
        a_distinct, a_tags, a_empty, a_joined = _stats(after)
        out = self.stdout.write
        out(f"Books:                                {len(rows)}")
        out(f"Books whose genres change:            {len(changed)}")
        out("                                      before    after")
        out(f"Distinct genres (ignoring case):  {b_distinct:>9} {a_distinct:>8}")
        out(f"Genre tags in total:              {b_tags:>9} {a_tags:>8}")
        out(f"Books with a joined value (, or /): {b_joined:>7} {a_joined:>8}")
        out(f"Books with no genres:             {b_empty:>9} {a_empty:>8}")
        top = Counter(g for genres in after for g in genres).most_common(10)
        out("Most common genres after: " + ", ".join(f"{g} ({n})" for g, n in top))

        if dry_run:
            out("Dry run: nothing was changed.")
            return
        for start in range(0, len(changed), BATCH_SIZE):
            batch = [
                Book(pk=book_id, genres=new) for book_id, new in changed[start : start + BATCH_SIZE]
            ]
            with transaction.atomic():
                Book.objects.bulk_update(batch, ["genres"])
        out(self.style.SUCCESS(f"Updated genres on {len(changed)} books."))

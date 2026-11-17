"""Fill in missing descriptions and genres from Open Library (C-6). Run nightly by GitHub
Actions (.github/workflows/jobs-nightly.yml), after the imports job.

    python manage.py enrich_books [--max-minutes 15] [--limit N]

Prints aggregate counts only (no titles), then the catalog's coverage, so we know how
many books recommendations (R-1) will have text for.
"""

import time

from django.core.management.base import BaseCommand

from catalog.services.enrichment import coverage, enrich_books


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole} ({part / whole:.0%})" if whole else "0 of 0"


class Command(BaseCommand):
    help = "Fill in missing book descriptions and genres from Open Library."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-minutes",
            type=float,
            default=15,
            help="Stop looking books up after this long (the job has a hard timeout).",
        )
        parser.add_argument("--limit", type=int, default=None, help="At most N books.")

    def handle(self, *args, max_minutes: float, limit: int | None, **options):
        report = enrich_books(stop_at=time.monotonic() + max_minutes * 60, limit=limit)
        out = self.stdout.write
        out(f"Books looked up:              {report.checked}")
        out(f"  descriptions filled:        {report.descriptions}")
        out(f"  genres filled:              {report.genres}")
        out(f"  Open Library keys found:    {report.work_keys}")
        out(f"  author keys filled:         {report.author_keys}")
        out(f"  not found in Open Library:  {report.not_found}")
        if report.duplicate_works:
            out(
                f"  work already on another catalog book: {report.duplicate_works} "
                "(review with merge_duplicate_books --dry-run)"
            )
        if report.duplicate_authors:
            out(
                f"  author key already on another author row: {report.duplicate_authors} "
                "(the same author under another spelling; left as is)"
            )
        if report.failed:
            out(self.style.WARNING(f"  lookups failed (retried next run): {report.failed}"))
        if report.stopped:
            out(self.style.WARNING(f"Stopped early: {report.stopped}."))

        cover = coverage()
        out("\nCatalog coverage after this run:")
        out(f"  still without a description: {_share(cover.without_description, cover.books)}")
        out(f"  still without genres:        {_share(cover.without_genres, cover.books)}")
        if cover.unreachable:
            out(f"  missing data, no Open Library key or ISBN to look up: {cover.unreachable}")

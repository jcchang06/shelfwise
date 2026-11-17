"""Finish or resume every unfinished import. Run nightly by GitHub Actions
(.github/workflows/jobs-nightly.yml) for imports whose page was closed early or that
paused when the Google budget ran out.

    python manage.py run_pending_imports [--max-minutes 20]
"""

import time

from django.core.management.base import BaseCommand

from imports.models import GoodreadsImport
from imports.processing import ImportBusyError, process_import_batch

UNFINISHED = (
    GoodreadsImport.Status.PENDING,
    GoodreadsImport.Status.RUNNING,
    GoodreadsImport.Status.PAUSED,
)


class Command(BaseCommand):
    help = "Process every pending, running or paused Goodreads import."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-minutes",
            type=float,
            default=20,
            help="Stop starting new batches after this long (the job has a hard timeout).",
        )

    def handle(self, *args, max_minutes: float, **options):
        stop_at = time.monotonic() + max_minutes * 60
        ids = list(
            GoodreadsImport.objects.filter(status__in=UNFINISHED)
            .order_by("created_at")
            .values_list("pk", flat=True)
        )
        if not ids:
            self.stdout.write("No unfinished imports.")
            return
        for import_id in ids:
            status = None
            while time.monotonic() < stop_at:
                try:
                    goodreads_import = process_import_batch(import_id)
                except ImportBusyError:
                    self.stdout.write(f"Import {import_id}: busy elsewhere, skipped.")
                    break
                status = goodreads_import.status
                if status != GoodreadsImport.Status.RUNNING:
                    break
            self.stdout.write(f"Import {import_id}: {status or 'not started (out of time)'}")
            if status == GoodreadsImport.Status.PAUSED:
                # The budget is shared: if one import paused on it, the rest would too.
                self.stdout.write("Google budget used up for today; stopping.")
                break

"""Run one import to completion (or until it pauses), batch after batch.

python manage.py run_import <import id>
"""

from django.core.management.base import BaseCommand, CommandError

from imports.models import GoodreadsImport
from imports.processing import ImportBusyError, process_import_batch


class Command(BaseCommand):
    help = "Process a Goodreads import until it's done or paused."

    def add_arguments(self, parser):
        parser.add_argument("import_id", type=int)

    def handle(self, *args, import_id: int, **options):
        if not GoodreadsImport.objects.filter(pk=import_id).exists():
            raise CommandError(f"No import with id {import_id}.")
        while True:
            try:
                goodreads_import = process_import_batch(import_id)
            except ImportBusyError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Import {import_id}: {goodreads_import.status}, "
                f"{goodreads_import.processed_rows}/{goodreads_import.total_rows} rows"
            )
            if goodreads_import.status != GoodreadsImport.Status.RUNNING:
                break
        if goodreads_import.status == GoodreadsImport.Status.PAUSED:
            self.stdout.write(self.style.WARNING(f"Paused: {goodreads_import.error}"))

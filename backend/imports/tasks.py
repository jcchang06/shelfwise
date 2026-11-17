"""Celery task for LOCAL Docker only (IMPORTS_USE_CELERY=true). Production has no worker;
the import page and the nightly job run batches instead. Celery is a dev-only dependency,
so nothing in production imports this module."""

from celery import shared_task

from .models import GoodreadsImport
from .processing import ImportBusyError, process_import_batch


@shared_task
def run_import_task(import_id: int) -> str:
    """Process batch after batch until the import is done or paused."""
    while True:
        try:
            goodreads_import = process_import_batch(import_id)
        except ImportBusyError:
            return "busy"
        if goodreads_import.status != GoodreadsImport.Status.RUNNING:
            return goodreads_import.status

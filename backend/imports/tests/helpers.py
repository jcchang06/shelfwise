"""Shared builders for import tests (synthetic data only)."""

from accounts.tests.factories import UserFactory
from imports.models import GoodreadsImport, ImportRow


def make_import(user=None, **fields) -> GoodreadsImport:
    return GoodreadsImport.objects.create(user=user or UserFactory(), **fields)


def make_row(goodreads_import: GoodreadsImport, number: int = 1, **fields) -> ImportRow:
    values = {
        "goodreads_import": goodreads_import,
        "row_number": number,
        "goodreads_book_id": str(9000000 + number),
        "title": f"Synthetic Book {number}",
        "author": "Mara Vell",
        "status": "want_to_read",
    }
    values.update(fields)
    row = ImportRow.objects.create(**values)
    goodreads_import.total_rows = goodreads_import.rows.count()
    goodreads_import.save(update_fields=["total_rows"])
    return row

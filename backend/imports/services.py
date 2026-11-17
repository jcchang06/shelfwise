"""Creating an import from an uploaded export. Matching and processing come in later PRs."""

from django.db import transaction

from .csv_parser import ParsedRow, parse_goodreads_csv
from .models import GoodreadsImport, ImportRow


def _row(goodreads_import: GoodreadsImport, parsed: ParsedRow) -> ImportRow:
    notes = list(parsed.notes)
    if parsed.error:
        notes.insert(0, parsed.error)
    return ImportRow(
        goodreads_import=goodreads_import,
        row_number=parsed.row_number,
        goodreads_book_id=parsed.goodreads_book_id,
        title=parsed.title[:500] or "(untitled)",
        author=parsed.author[:255],
        additional_authors=parsed.additional_authors,
        isbn_13=parsed.isbn_13,
        page_count=parsed.page_count,
        year_published=parsed.year_published if parsed.year_published else None,
        series_name=parsed.series_name[:255],
        series_number=parsed.series_number,
        status=parsed.status,
        rating=parsed.rating,
        date_read=parsed.date_read,
        date_added=parsed.date_added,
        review=parsed.review,
        state=ImportRow.State.FAILED if parsed.error else ImportRow.State.PENDING,
        note=" ".join(notes),
    )


def create_import(user, data: bytes) -> GoodreadsImport:
    """Parse the uploaded bytes and store an import with its rows.

    The file itself is never written anywhere: only the parsed columns are kept (PRD
    privacy). Raises csv_parser.ImportFileError if the file is unusable, before anything
    is saved.
    """
    parsed_rows = parse_goodreads_csv(data)
    failed = sum(1 for p in parsed_rows if p.error)
    with transaction.atomic():
        goodreads_import = GoodreadsImport.objects.create(
            user=user,
            total_rows=len(parsed_rows),
            processed_rows=failed,  # failed rows need no processing
            failed_count=failed,
        )
        ImportRow.objects.bulk_create(_row(goodreads_import, p) for p in parsed_rows)
    return goodreads_import

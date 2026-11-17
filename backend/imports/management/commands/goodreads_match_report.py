"""Measure how well a Goodreads export matches, without touching any shelf (Phase 2 gate:
90%+ of rows matched automatically).

    python manage.py goodreads_match_report ~/Downloads/goodreads_library_export.csv
    python manage.py goodreads_match_report <path> --show-unmatched   # titles, locally only

It runs the real matching pipeline (catalog, Open Library batches, Google within the
import budget), so matched books ARE saved to the catalog, which makes a later real import
of the same file mostly catalog hits. Nothing is written to any shelf, no import is
created, and the file itself is only read. Output is aggregate unless --show-unmatched.
"""

import re
import time
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from imports.budget import google_calls_used
from imports.csv_parser import ImportFileError, parse_goodreads_csv
from imports.matching import MatchPausedError, MatchRetryLaterError, match_row, prefetch_isbns
from imports.models import GoodreadsImport, ImportRow
from imports.services import _row

GATE = 0.90
CHUNK = 200  # rows per ISBN prefetch, like processing batches


def reason_category(note: str) -> str:
    """Group unmatched notes without row-specific detail (titles, ISBNs)."""
    if "belongs to" in note:
        return "ISBN points at another book in Open Library"
    if "wasn't found" in note and "No book with this title" in note:
        return "ISBN not found, and no exact title + author match"
    if "similar books but none" in note:
        return "Google found similar books, but no exact title + author"
    if "No book with this title" in note:
        return "No exact title + author match"
    if "No author" in note:
        return "No author to search by"
    if "couldn't be reached" in note:
        return "Book source unreachable"
    return re.sub(r"\d{10,13}", "<isbn>", note)[:80] or "(no reason)"


class Command(BaseCommand):
    help = "Report the automatic match rate for a Goodreads export (no shelf changes)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--limit", type=int, default=None, help="Only the first N rows.")
        parser.add_argument(
            "--show-unmatched",
            action="store_true",
            help="Also list unmatched titles (local use only; never paste into PRs).",
        )

    def handle(self, *args, path: Path, limit: int | None, show_unmatched: bool, **options):
        try:
            parsed = parse_goodreads_csv(path.expanduser().read_bytes())
        except FileNotFoundError as exc:
            raise CommandError(f"No file at {path}") from exc
        except ImportFileError as exc:
            raise CommandError(str(exc)) from exc
        if limit:
            parsed = parsed[:limit]

        holder = GoodreadsImport()  # unsaved: rows are never stored
        rows = [_row(holder, p) for p in parsed]
        importable = [r for r in rows if r.state != ImportRow.State.FAILED]
        methods: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        unmatched: list[ImportRow] = []
        google_before = google_calls_used()
        paused_at = None

        for start in range(0, len(importable), CHUNK):
            chunk = importable[start : start + CHUNK]
            prefetched = prefetch_isbns(chunk)
            for index, row in enumerate(chunk):
                for _attempt in range(5):
                    try:
                        match = match_row(row, prefetched)
                        break
                    except MatchRetryLaterError:
                        self.stdout.write("Google rate limit; waiting 30s…")
                        time.sleep(30)
                    except MatchPausedError as exc:
                        paused_at = (start + index, str(exc))
                        break
                else:
                    paused_at = (start + index, "still rate limited after 5 tries")
                if paused_at:
                    break
                if match.book:
                    methods[match.method] += 1
                else:
                    reasons[reason_category(match.note)] += 1
                    row.note = match.note
                    unmatched.append(row)
            if paused_at:
                break

        checked = sum(methods.values()) + sum(reasons.values())
        matched = sum(methods.values())
        out = self.stdout.write
        out(f"Rows in file:            {len(rows)}")
        out(f"Failed at parsing:       {len(rows) - len(importable)}")
        out(f"Checked:                 {checked}")
        if paused_at:
            out(
                self.style.WARNING(
                    f"Stopped early ({paused_at[1]}); {len(importable) - checked} rows not checked."
                )
            )
        out("\nMatched automatically, by method:")
        for method, label in ImportRow.MatchMethod.choices:
            if methods[method]:
                out(f"  {label:<34} {methods[method]:>5}")
        out(f"\nUnmatched: {sum(reasons.values())}")
        for reason, count in reasons.most_common():
            out(f"  {reason:<58} {count:>5}")
        rate = matched / checked if checked else 0
        style = self.style.SUCCESS if rate >= GATE else self.style.WARNING
        out(style(f"\nMatch rate: {matched}/{checked} = {rate:.1%} (gate {GATE:.0%})"))
        out(f"Google calls counted today for imports: {google_calls_used() - google_before}")

        if show_unmatched:
            out("\nUnmatched rows (local only):")
            for row in unmatched:
                out(
                    f"  row {row.row_number}: {row.title} | {row.author} | "
                    f"isbn={row.isbn_13 or '-'} | {row.note}"
                )

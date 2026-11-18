"""Nightly recommendation build (R-1, R-2, R-3, R-5). Run by GitHub Actions after the
enrichment job (.github/workflows/jobs-nightly.yml); needs requirements-jobs.txt.

    python manage.py build_recommendations

Reads a snapshot in one short transaction, closes the connection, computes TF-IDF picks
and similar books in memory, then writes a new run in batches. Prints counts only.
"""

import time
from collections import Counter

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.seed.readonly import release_connection
from recommendations.build import compute, read_snapshot, write


def _total(effects, attr: str) -> int:
    return sum(getattr(e, attr) for e in effects)


class Command(BaseCommand):
    help = "Rebuild personal picks and similar books from the catalog (TF-IDF)."

    def handle(self, *args, **options):
        call_command("dbinfo", stdout=self.stdout)
        started_at = timezone.now()
        began = time.perf_counter()
        snapshot = read_snapshot()
        read_seconds = time.perf_counter() - began
        release_connection()  # nothing is held open while computing

        results = compute(snapshot)
        report = write(results, started_at)

        out = self.stdout.write
        out(f"Books in the catalog:           {len(snapshot.books)}")
        out(f"Books with text (scored):       {len(results.model.books)}")
        out(f"Vocabulary:                     {results.model.vocabulary}")
        excluded = Counter(reason for reason in results.model.excluded if reason)
        out(
            "Never recommended:              "
            + (", ".join(f"{r} {n}" for r, n in sorted(excluded.items())) or "none")
        )
        out(f"Readers with picks:             {report.users_with_picks}")
        if report.users_without_picks:
            out(
                f"Readers with no picks yet:      {len(report.users_without_picks)} "
                "(no rated or finished books with text)"
            )
        out(f"Picks written:                  {report.picks}")
        effects = list(results.boost.values())
        boosted, in_top = _total(effects, "boosted"), _total(effects, "in_top")
        moved, entered, left = (_total(effects, a) for a in ("moved", "entered", "left"))
        params = results.model.params
        out(
            f"Series boost ({params.series_boost}): {boosted} books boosted, {in_top} in the "
            f"top {params.picks}; {moved} picks moved, {entered} entered, {left} left"
        )
        out(f"Similar-book rows written:      {report.neighbour_rows}")
        out(f"Old runs deleted:               {report.old_runs_deleted}")
        out(
            f"Seconds: read {read_seconds:.1f}, compute {results.seconds:.1f}, "
            f"write {report.seconds:.1f}"
        )

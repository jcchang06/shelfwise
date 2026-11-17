"""Build the catalog seed (C-3) from Open Library dumps. Reads the database (catalog for
duplicates, shelf entries for the reader's genres) but never writes to it; loading the
file is seed_catalog's job.

    # dumps from https://openlibrary.org/developers/dumps in backend/dumps/ (gitignored):
    # ol_dump_reading-log_*.txt.gz, ol_dump_ratings_*.txt.gz (optional),
    # ol_dump_works_*.txt.gz, ol_dump_authors_*.txt.gz
    python manage.py build_catalog_seed --dumps dumps --out dumps/seed.jsonl.gz

Point it at the database the seed is for (run dbinfo first): the reader's genres come
from that database's shelf entries. Output is aggregate counts only; --show-genres also
prints those genres (local use only; never paste into PRs or logs).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.seed import dumps
from catalog.seed.build import MIN_DESCRIPTION_CHARS, build_seed, taste_genres, write_seed
from catalog.services.types import BookSourceError


class Command(BaseCommand):
    help = "Choose catalog seed books from Open Library dumps and write a seed file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dumps", dest="dumps_dir", type=Path, required=True, help="Folder with the dumps."
        )
        parser.add_argument("--out", type=Path, required=True, help="Seed file (.jsonl.gz).")
        parser.add_argument("--target", type=int, default=10_000)
        parser.add_argument(
            "--candidates",
            type=int,
            default=60_000,
            help="Most popular works to consider (most fail the filters).",
        )
        parser.add_argument("--show-genres", action="store_true")

    def handle(self, *args, dumps_dir: Path, out: Path, target, candidates, show_genres, **opts):
        genres = taste_genres()
        try:
            books, report = build_seed(
                dumps_dir, target, candidates, genres, progress=self.stdout.write
            )
        except (dumps.DumpError, BookSourceError) as exc:
            raise CommandError(str(exc)) from exc
        write_seed(out, books)

        out_ = self.stdout.write
        r = report
        out_(f"\nWorks in the reading log:        {r.reading_log_works}")
        out_(f"Already in the catalog (skipped): {r.already_in_catalog}")
        out_(f"Candidates considered:            {r.candidates}")
        out_(f"  of which recent, from search:   {r.recent_candidates}")
        out_("Dropped:")
        for label, count in [
            ("not in the works dump", r.not_in_works_dump),
            (f"description under {MIN_DESCRIPTION_CHARS} characters", r.short_description),
            ("no usable genres", r.no_genres),
            ("no author (or no author name)", r.no_author),
            ("not found by search", r.not_in_search),
            ("no edition in the search language", r.other_language),
            ("same book as one in the catalog", r.duplicate_of_catalog),
            ("another copy of a work in the seed", r.duplicate_in_seed),
        ]:
            out_(f"  {label:<38} {count:>7}")
        out_(f"Eligible:                         {r.eligible}")
        out_(f"\nSeed: {len(books)} of {r.target} books")
        out_(f"  popular:  {r.pools.get('popular', 0)}")
        out_(f"  my genres ({r.taste_genres} genres): {r.pools.get('taste', 0)}")
        out_(f"  recent (first published {r.recent_from_year}+): {r.pools.get('recent', 0)}")
        for pool, missing in r.shortfalls.items():
            out_(self.style.WARNING(f"  short by {missing} in '{pool}' (filled from popular)"))
        out_(f"Written to {out}")
        if show_genres:
            out_(f"\nYour genres (local only): {', '.join(genres) or '(none)'}")

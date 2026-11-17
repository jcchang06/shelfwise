"""Load the catalog seed built by build_catalog_seed (C-3), or remove it.

    python manage.py seed_catalog dumps/seed.jsonl.gz --dry-run   # counts only, no writes
    python manage.py seed_catalog dumps/seed.jsonl.gz             # load (safe to re-run)
    python manage.py seed_catalog --remove --dry-run              # what removal would delete
    python manage.py seed_catalog --remove --apply <token>        # delete exactly that

The first line printed is the database (dbinfo). Removal deletes only seeded books with no
shelf entry and no reading log, plus authors left with no books, and only with the token
from a dry run of that exact plan (like merge_duplicate_books).
"""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from catalog.seed.load import load_seed, removal_plan, remove_seed


class Command(BaseCommand):
    help = "Load (or remove) the catalog seed. Prints the database first."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path, nargs="?", help="Seed file (.jsonl.gz).")
        parser.add_argument("--dry-run", action="store_true", help="Report only; no writes.")
        parser.add_argument("--remove", action="store_true", help="Remove unshelved seed books.")
        parser.add_argument("--apply", metavar="TOKEN", help="With --remove: the dry run's token.")

    def handle(self, *args, path, dry_run, remove, apply, **options):
        call_command("dbinfo", stdout=self.stdout)
        if remove:
            self._remove(dry_run, apply)
            return
        if apply:
            raise CommandError("--apply is only for --remove.")
        if path is None:
            raise CommandError("Give the seed file to load, or use --remove.")
        if not path.exists():
            raise CommandError(f"No file at {path}")

        report = load_seed(path, dry_run=dry_run, progress=self.stdout.write)
        out = self.stdout.write
        r = report
        verb = "Would add" if dry_run else "Added"
        out(f"Records in the file:            {r.records}")
        out(f"{verb} books:                  {r.created}")
        pools = ", ".join(f"{name} {count}" for name, count in sorted(r.pools.items()))
        out(f"  by pool:                      {pools or '-'}")
        out("Skipped:")
        out(f"  same Open Library work        {r.existing_key}")
        out(f"  same ISBN-13                  {r.existing_isbn}")
        out(f"  same title + first author     {r.existing_title_author}")
        out(f"  invalid record                {r.invalid}")
        out(
            f"Authors: {r.authors_created} new, {r.authors_matched} already in the catalog "
            f"({r.authors_keyed} of them given their Open Library key)"
        )
        if dry_run:
            out("Dry run: nothing was changed.")
        else:
            out(self.style.SUCCESS("Done. Check with: manage.py merge_duplicate_books --dry-run"))

    def _remove(self, dry_run: bool, token: str | None) -> None:
        if not dry_run and not token:
            raise CommandError("Run --remove --dry-run first, then --remove --apply <token>.")
        plan = removal_plan()
        if dry_run:
            self.stdout.write(
                f"Would remove {len(plan.book_ids)} seeded book(s) nobody has shelved or "
                f"logged, and {len(plan.author_ids)} author(s) left with no books. "
                "Nothing was changed."
            )
            if plan.book_ids:
                self.stdout.write(f"To remove exactly this: --remove --apply {plan.token}")
            return
        if token != plan.token:
            raise CommandError(
                "The catalog changed since that dry run (or the token is wrong). "
                "Run --remove --dry-run again and review it."
            )
        books, authors = remove_seed(plan)
        self.stdout.write(self.style.SUCCESS(f"Removed {books} book(s) and {authors} author(s)."))

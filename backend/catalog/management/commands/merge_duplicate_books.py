"""Find (and, only after a reviewed dry run, merge) duplicate catalog books.

    python manage.py merge_duplicate_books --dry-run
    python manage.py merge_duplicate_books --apply <token from the dry run>

There is deliberately no way to merge without a dry run: --apply needs the token the dry
run printed, and refuses if the catalog changed since (the plan would differ).
"""

from django.core.management.base import BaseCommand, CommandError

from catalog.services.duplicates import find_duplicate_groups, merge_group, plan_token


class Command(BaseCommand):
    help = "Report duplicate catalog books (--dry-run), then merge exactly that plan (--apply)."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Report only; change nothing.")
        mode.add_argument("--apply", metavar="TOKEN", help="Merge the plan from a dry run.")

    def handle(self, *args, **options):
        if not options["dry_run"] and not options["apply"]:
            raise CommandError(
                "Run with --dry-run first, review the report, then --apply <token> from it."
            )
        groups = find_duplicate_groups()
        token = plan_token(groups)

        if options["dry_run"]:
            self._report(groups, token)
            return

        if options["apply"] != token:
            raise CommandError(
                "The catalog changed since that dry run (or the token is wrong), so the plan "
                "would be different. Run --dry-run again and review the new report."
            )
        merged = [g for g in groups if g.mergeable]
        for group in merged:
            merge_group(group)
        skipped = len(groups) - len(merged)
        self.stdout.write(
            self.style.SUCCESS(
                f"Merged {sum(len(g.duplicates) for g in merged)} duplicate book(s) into "
                f"{len(merged)} keeper(s). Skipped {skipped} group(s) with conflicts."
            )
        )

    def _report(self, groups, token):
        if not groups:
            self.stdout.write("No duplicate books found. Nothing to merge.")
            return
        for group in groups:
            k = group.keeper
            self.stdout.write(f"\n“{k.title}” ({group.author_key})")
            self.stdout.write(
                f"  keep   #{k.id}  google={k.google_books_id or '-'}  "
                f"openlibrary={k.open_library_key or '-'}  isbn={k.isbn_13 or '-'}"
            )
            for d in group.duplicates:
                self.stdout.write(
                    f"  merge  #{d.id}  google={d.google_books_id or '-'}  "
                    f"openlibrary={d.open_library_key or '-'}  isbn={d.isbn_13 or '-'}  "
                    f"title=“{d.title}”"
                )
            for conflict in group.conflicts:
                self.stdout.write(self.style.WARNING(f"  NOT MERGED: {conflict}"))
        mergeable = [g for g in groups if g.mergeable]
        self.stdout.write(
            f"\n{len(groups)} group(s); {len(mergeable)} can be merged "
            f"({sum(len(g.duplicates) for g in mergeable)} book(s)). Nothing was changed."
        )
        if mergeable:
            self.stdout.write(
                f"To merge exactly this plan: manage.py merge_duplicate_books --apply {token}"
            )

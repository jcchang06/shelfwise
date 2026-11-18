"""Judge recommendation quality (Phase 3 gate), read-only. Prints the database first.

    python manage.py recommendation_profiles_report                    # held-out check
    python manage.py recommendation_profiles_report --genre-weight 2 --no-phrases
    python manage.py recommendation_profiles_report --profiles        # titles: local only
    python manage.py recommendation_profiles_report --mine            # titles: local only

Held-out check, per reader with enough 4+ star books (counts only): hide a random 20% of
them (one fixed seed per run, --seeds of them), build picks from the rest with the hidden
books treated as unread, and count how many come back in the top 20 and top 50. Reports
each seed and the average, next to what random picks would score, so the genre weight
and phrases can be tuned against a number.

--profiles builds picks for three synthetic readers (romance; fantasy and science
fiction; history and biography) from catalog books, and --mine prints your own picks.
Both print titles: for your eyes only, never paste them into PRs or logs.
"""

import random

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from catalog.seed.readonly import read_only_database, release_connection
from recommendations.build import read_snapshot
from recommendations.engine import Model, Params, ShelfItem, holdout

MIN_LIKED_FOR_HOLDOUT = 10
PROFILES = {
    "romance": {"romance", "contemporary romance", "romantic suspense"},
    "fantasy and science fiction": {"fantasy", "science fiction", "epic fantasy"},
    "history and biography": {"history", "biography", "memoir", "autobiography"},
}
PROFILE_BOOKS = 25


class Command(BaseCommand):
    help = "Held-out hit rate and sample picks for judging recommendations (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--seeds", type=int, default=5, help="Random hidden sets to average.")
        parser.add_argument("--genre-weight", type=int, default=Params.genre_weight)
        parser.add_argument("--no-phrases", action="store_true", help="Single words only.")
        parser.add_argument("--profiles", action="store_true", help="Synthetic readers (titles).")
        parser.add_argument("--mine", action="store_true", help="Your own picks (titles).")

    def handle(self, *args, seeds, genre_weight, no_phrases, profiles, mine, **options):
        call_command("dbinfo", stdout=self.stdout)
        with read_only_database():
            snapshot = read_snapshot()
            release_connection()
        params = Params(genre_weight=genre_weight, phrases=not no_phrases)
        model = Model(snapshot.books, params)
        weights = settings.DNF_REASON_WEIGHTS
        out = self.stdout.write
        out(
            f"Model: {len(model.books)} books with text, vocabulary {model.vocabulary}, "
            f"genre weight {genre_weight}, phrases {'on' if params.phrases else 'off'}"
        )

        readers = 0
        for _user_id, shelf in sorted(snapshot.shelves.items()):
            result = holdout(model, shelf, weights, seeds=list(range(seeds)))
            if result.liked < MIN_LIKED_FOR_HOLDOUT:
                continue
            readers += 1
            out(
                f"\nReader {readers}: {result.liked} books at 4+ stars; "
                f"{result.hidden} hidden per seed"
            )
            for k in sorted(result.hits):
                per_seed = ", ".join(str(h) for h in result.hits[k])
                out(
                    f"  hits in top {k}: {per_seed}  (average {result.average(k):.1f} = "
                    f"{result.rate(k):.1%} of hidden; random picks ~{result.random_rate(k):.2%})"
                )
        if not readers:
            out(f"\nNo reader has {MIN_LIKED_FOR_HOLDOUT}+ books at 4+ stars with text yet.")

        books = {b.id: b for b in model.books}
        if profiles:
            out("\nSynthetic readers (local only; never paste titles into PRs):")
            for name, genres in PROFILES.items():
                pool = [b for b in model.books if {g.casefold() for g in b.genres} & genres]
                chosen = random.Random(7).sample(pool, min(PROFILE_BOOKS, len(pool)))  # noqa: S311
                shelf = [ShelfItem(b.id, "finished", 5, "", b.key) for b in chosen]
                picks = model.picks(shelf, weights)
                matching = sum(
                    1 for p in picks if {g.casefold() for g in books[p.book_id].genres} & genres
                )
                out(
                    f"\n  {name}: {len(chosen)} liked books; "
                    f"{matching}/{len(picks)} picks share its genres"
                )
                for p in picks[:10]:
                    book = books[p.book_id]
                    out(f"    {p.score:.2f}  {book.title}  [{', '.join(book.genres[:3])}]")
        if mine:
            out("\nYour picks (local only):")
            for user_id, shelf in sorted(snapshot.shelves.items()):
                for p in model.picks(shelf, weights):
                    book, because = books[p.book_id], books.get(p.because_of)
                    out(
                        f"  user {user_id}  {p.score:.2f}  {book.title}  "
                        f"(like {because.title if because else '?'})"
                    )

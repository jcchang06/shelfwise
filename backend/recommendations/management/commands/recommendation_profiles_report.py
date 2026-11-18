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
from collections import Counter

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from catalog.seed.readonly import read_only_database, release_connection
from recommendations.build import read_snapshot
from recommendations.engine import Model, Params, ShelfItem, holdout

MIN_LIKED_FOR_HOLDOUT = 10
# --no-<flag> switches off one rule added in #42 (Params field = flag with "_").
RULE_FLAGS = {
    "picture-books": "Don't exclude picture books.",
    "non-latin": "Don't exclude non-Latin titles.",
    "marker-only": "Don't exclude marker-only titles.",
    "description-series": "Ignore series found in descriptions.",
    "title-number-series": "Ignore trailing Book N / #N in titles.",
    "next-in-series": "Don't limit started series to the next unread book.",
    "dnf-series": "Don't skip series with a DNF.",
}
MISS_REASONS = {
    "ranked_below": "eligible, but scored below the cut",
    "not_next_in_series": "started series: not the next unread book",
    "series_first_book_instead": "unstarted series: replaced by its first book",
    "series_first_book_missing": "unstarted series, first book not in the catalog",
    "book_n_skip": "Book N title, series unknown",
    "dnf_series": "a series with a DNF",
    "author_cap": "two picks by the same author already",
    "copy_on_shelf": "another copy of it is on the shelf",
    "copy_picked": "another copy was picked",
    "picture_book": "excluded: picture book",
    "non_latin": "excluded: non-Latin title",
    "foreign": "excluded: not English",
    "omnibus": "excluded: box set",
    "not_a_book": "excluded: not a book",
    "marker_only": "excluded: marker-only title",
    "no_text": "no description or genres",
}
PROFILES = {
    "romance": {"romance", "contemporary romance", "romantic suspense"},
    "fantasy and science fiction": {"fantasy", "science fiction", "epic fantasy"},
    "history and biography": {"history", "biography", "memoir", "autobiography"},
}
PROFILE_BOOKS = 25


def _mean(effects, attr: str) -> float:
    return sum(getattr(e, attr) for e in effects) / len(effects)


class Command(BaseCommand):
    help = "Held-out hit rate and sample picks for judging recommendations (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--seeds", type=int, default=5, help="Random hidden sets to average.")
        parser.add_argument("--genre-weight", type=int, default=Params.genre_weight)
        parser.add_argument("--no-phrases", action="store_true", help="Single words only.")
        parser.add_argument(
            "--series-boost", type=float, default=Params.series_boost, help="R-6 next-in-series."
        )
        parser.add_argument("--profiles", action="store_true", help="Synthetic readers (titles).")
        # Switch off one #42 rule at a time to measure it.
        for flag, help_text in RULE_FLAGS.items():
            parser.add_argument(f"--no-{flag}", action="store_true", help=help_text)
        parser.add_argument(
            "--no-series-tails",
            action="store_true",
            help="Hide random books only (the old simulation; can make impossible readers).",
        )
        parser.add_argument("--mine", action="store_true", help="Your own picks (titles).")

    def handle(
        self, *args, seeds, genre_weight, no_phrases, series_boost, profiles, mine, **options
    ):
        off = {flag for flag in RULE_FLAGS if options[f"no_{flag.replace('-', '_')}"]}
        call_command("dbinfo", stdout=self.stdout)
        with read_only_database():
            snapshot = read_snapshot()
            release_connection()
        params = Params(
            genre_weight=genre_weight,
            phrases=not no_phrases,
            series_boost=series_boost,
            **{flag.replace("-", "_"): False for flag in off},
        )
        model = Model(snapshot.books, params)
        weights = settings.DNF_REASON_WEIGHTS
        out = self.stdout.write
        out(
            f"Model: {len(model.books)} books with text, vocabulary {model.vocabulary}, "
            f"genre weight {genre_weight}, phrases {'on' if params.phrases else 'off'}, "
            f"series boost {series_boost}"
        )
        out(
            "Rules off: "
            + (", ".join(sorted(off)) or "none")
            + ("; random hiding (no series tails)" if options["no_series_tails"] else "")
        )
        excluded = Counter(reason for reason in model.excluded if reason)
        out(
            "Never recommended: "
            + ", ".join(f"{reason} {count}" for reason, count in sorted(excluded.items()))
            + f"; books with a known series: {sum(1 for b in model.books if b.series)}"
        )

        readers = 0
        for _user_id, shelf in sorted(snapshot.shelves.items()):
            result = holdout(
                model,
                shelf,
                weights,
                seeds=list(range(seeds)),
                series_tails=not options["no_series_tails"],
            )
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
            if result.boost:
                b = result.boost
                boosted, in_top = _mean(b, "boosted"), _mean(b, "in_top")
                moved, entered, left = (_mean(b, a) for a in ("moved", "entered", "left"))
                added = ", ".join(
                    f"top {k} {n:+d}" for k, n in sorted(result.hits_from_boost.items())
                )
                out(
                    f"  series boost {params.series_boost}: {boosted:.1f} books boosted per seed, "
                    f"{in_top:.1f} of them in the top {max(result.hits)}; {moved:.1f} picks "
                    f"moved, {entered:.1f} entered, {left:.1f} left; hits it added: {added}"
                )
            if result.tail_hidden:
                tails = sum(result.tail_hidden) / len(result.tail_hidden)
                out(f"  later series books also hidden (not targets): {tails:.1f} per seed")
            total = sum(result.misses.values())
            out(f"  why targets missed the top {max(result.hits)} ({total} over all seeds):")
            for reason, count in result.misses.most_common():
                out(f"    {reason:<28} {count:>4}  ({MISS_REASONS.get(reason, '')})")
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

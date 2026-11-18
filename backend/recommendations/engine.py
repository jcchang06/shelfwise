"""TF-IDF recommendations (R-1, R-2, R-3, R-5, R-6): pure computation, no database access.

- Text per book: title, description and genres, each genre as one token (`genre_romance`)
  repeated `genre_weight` times (default 1: it beat 3 and 5 in the held-out check).
  English stop words removed; single words and two-word phrases ("slow burn", "found
  family") unless phrases=False. Rows are L2-normalized, so a dot product is cosine
  similarity.
- Personal picks (R-2): a candidate's score is the mean of its `top_liked` highest
  similarities to the reader's liked books (robust to mixed tastes, where one averaged
  profile would drift between them), minus the DNF penalty (R-5): the largest of
  weight(reason) x similarity over the reader's DNF books.
- Never recommended: anything on the shelf; another copy of a shelved book (same title +
  first author key, or the same title when the shelved copy has no author); books failing
  a candidates.py rule. At most `author_cap` picks per author, counting every credited
  author.
- Series (R-6): in a series the reader hasn't started, a later book is replaced by the
  series' first book in the catalog (or skipped). In a series they have started (a book
  finished or being read), only the next unread book is recommended, boosted by
  `series_boost` when they rated what they finished 3+ stars or not at all. Series with a
  DNF are skipped. A "Book N" title in an unknown series is skipped when N > 1.
- Every rule added in the #42 follow-up can be switched off in Params, to measure it.
- Liked books: rated 4+ stars. With fewer than `min_liked`, also finished books rated 3+
  or unrated, and books being read now.
- More like this (R-3): each book's `neighbours` most similar books, never itself or
  another copy of itself.
"""

import random
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .candidates import UNKNOWN_SERIES, exclusion_reasons

Key = tuple[str, str]  # normalize.title_author_key(title, first author)


# A key's author part for books with no author: two such books never share a key.
NO_AUTHOR = "#"


@dataclass(frozen=True)
class BookText:
    id: int
    title: str
    description: str
    genres: tuple[str, ...]
    authors: tuple[str, ...]  # every credited author, normalized, for the per-author cap
    key: Key
    series: str = ""  # candidates.series_key, "" if not known to be in a series
    series_number: float | None = None
    page_count: int | None = None
    series_source: str = ""  # candidates.SERIES_SOURCES; "catalog" when unknown


@dataclass(frozen=True)
class ShelfItem:
    book_id: int
    status: str
    rating: int | None
    dnf_reason: str
    key: Key
    series: str = ""
    series_number: float | None = None


def title_only(key: Key) -> bool:
    return key[1].startswith(NO_AUTHOR)


@dataclass(frozen=True)
class Params:
    genre_weight: int = 1
    phrases: bool = True
    top_liked: int = 3
    picks: int = 20
    author_cap: int = 2
    min_liked: int = 5
    neighbours: int = 10
    max_features: int = 100_000
    series_boost: float = 0.1
    # Rules from the #42 follow-up, each switchable to measure its effect.
    picture_books: bool = True
    non_latin: bool = True
    marker_only: bool = True
    description_series: bool = True
    title_number_series: bool = True
    next_in_series: bool = True
    dnf_series: bool = True

    def disabled_rules(self) -> set[str]:
        flags = {
            "picture_book": self.picture_books,
            "non_latin": self.non_latin,
            "marker_only": self.marker_only,
        }
        return {rule for rule, on in flags.items() if not on}

    def disabled_series_sources(self) -> set[str]:
        flags = {"description": self.description_series, "title_number": self.title_number_series}
        return {source for source, on in flags.items() if not on}


@dataclass(frozen=True)
class Pick:
    book_id: int
    score: float
    because_of: int  # the liked book it's most like


def has_text(book: BookText) -> bool:
    return bool(book.description.strip() or book.genres)


def _genre_token(genre: str) -> str:
    return "genre_" + "_".join(genre.casefold().split())


def document(book: BookText, genre_weight: int) -> str:
    genres = " ".join([_genre_token(g) for g in book.genres] * genre_weight)
    return f"{book.title} {book.description} {genres}"


def liked_books(shelf: list[ShelfItem], min_liked: int) -> list[ShelfItem]:
    liked = [s for s in shelf if s.rating is not None and s.rating >= 4]
    if len(liked) >= min_liked:
        return liked
    extra = [
        s
        for s in shelf
        if s not in liked
        and (
            (s.status == "finished" and (s.rating is None or s.rating >= 3))
            or s.status == "reading"
        )
    ]
    return liked + extra


class _SeriesState:
    """What the reader's shelf says about series (R-6). `series_of` gives a shelf item's
    effective (series, number), so a switched-off series source is ignored here too."""

    def __init__(self, shelf: list[ShelfItem], series_of, params: Params):
        named = []
        for s in shelf:
            name, number = series_of(s)
            if name and name != UNKNOWN_SERIES:
                named.append((s, name, number))
        self.dnf = (
            {name for s, name, _ in named if s.status == "dnf"} if params.dnf_series else set()
        )
        read = [
            (s, name, number)
            for s, name, number in named
            if s.status in ("finished", "reading") and name not in self.dnf
        ]
        # series -> highest book number finished or being read (0 if numbers are unknown)
        self.started: dict[str, float] = {}
        for _, name, number in read:
            self.started[name] = max(self.started.get(name, 0), number or 0)
        self.liked = {
            name
            for s, name, _ in read
            if s.status == "finished" and (s.rating is None or s.rating >= 3)
        }


@dataclass
class _Context:
    """Everything picks() decides with, kept so a miss can be explained the same way."""

    liked_rows: list[int]
    sims: np.ndarray
    score: np.ndarray
    shelved_ids: set[int]
    shelved_keys: set[Key]
    shelved_titles: set[str]
    series: _SeriesState
    next_rows: dict[str, int] = field(default_factory=dict)
    picked_keys: set[Key] = field(default_factory=set)
    per_author: Counter = field(default_factory=Counter)


class Model:
    """The TF-IDF matrix over every book with text."""

    def __init__(self, books: list[BookText], params: Params | None = None):
        params = params or Params()
        self.params = params
        self.books = [b for b in books if has_text(b)]
        self.row = {b.id: i for i, b in enumerate(self.books)}
        self.keys = [b.key for b in self.books]
        # Why each book can't be recommended (None: it can), ignoring switched-off rules.
        disabled = params.disabled_rules()
        self.reasons = [
            exclusion_reasons(b.title, b.description, b.genres, b.page_count) for b in self.books
        ]
        self.excluded = [
            next((reason for reason in reasons if reason not in disabled), None)
            for reasons in self.reasons
        ]
        # Each book's effective series, ignoring switched-off series sources.
        off = params.disabled_series_sources()
        self.series = [
            ("", None) if b.series_source in off else (b.series, b.series_number)
            for b in self.books
        ]
        # series -> [(number, row)], first book first, for replacing mid-series picks.
        self.series_rows: dict[str, list[tuple[float, int]]] = {}
        for r, (name, number) in enumerate(self.series):
            if name and name != UNKNOWN_SERIES and number is not None and not self.excluded[r]:
                self.series_rows.setdefault(name, []).append((number, r))
        for rows in self.series_rows.values():
            rows.sort()
        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 2) if params.phrases else (1, 1),
            min_df=2,
            max_df=0.5,
            sublinear_tf=True,
            max_features=params.max_features,
            # Words of 2+ characters, keeping apostrophes ("don't"). (S106: not a password.)
            token_pattern=r"(?u)\b\w[\w']+\b",  # noqa: S106
        )
        self.matrix = self.vectorizer.fit_transform(
            [document(b, params.genre_weight) for b in self.books]
        ).tocsr()

    @property
    def vocabulary(self) -> int:
        return len(self.vectorizer.vocabulary_)

    def _rows(self, book_ids) -> list[int]:
        return [self.row[i] for i in book_ids if i in self.row]

    def shelf_series(self, item: ShelfItem) -> tuple[str, float | None]:
        """A shelf item's effective series: its catalog book's, when that has text."""
        if item.book_id in self.row:
            return self.series[self.row[item.book_id]]
        return item.series, item.series_number

    # --- Picks -----------------------------------------------------------------------

    def _context(self, shelf: list[ShelfItem], dnf_weights: dict[str, float]) -> _Context | None:
        p = self.params
        liked_rows = self._rows(s.book_id for s in liked_books(shelf, p.min_liked))
        if not liked_rows:
            return None
        sims = (self.matrix @ self.matrix[liked_rows].T).toarray()  # books x liked
        k = min(p.top_liked, len(liked_rows))
        top = np.partition(sims, sims.shape[1] - k, axis=1)[:, -k:]
        score = top.mean(axis=1)

        dnf = [(s.book_id, dnf_weights.get(s.dnf_reason, 0.5)) for s in shelf if s.status == "dnf"]
        dnf_rows = [(self.row[b], w) for b, w in dnf if b in self.row and w > 0]
        if dnf_rows:
            rows, weights = zip(*dnf_rows, strict=True)
            penalty = (self.matrix @ self.matrix[list(rows)].T).toarray() * np.array(weights)
            score = score - penalty.max(axis=1)

        ctx = _Context(
            liked_rows=liked_rows,
            sims=sims,
            score=score,
            shelved_ids={s.book_id for s in shelf},
            shelved_keys={s.key for s in shelf},
            # A shelved copy with no author can only be recognised by its title.
            shelved_titles={s.key[0] for s in shelf if title_only(s.key)},
            series=_SeriesState(shelf, self.shelf_series, p),
        )
        if p.next_in_series:
            # The next unread book of each started series, boosted when liked (R-6).
            for name, read_up_to in ctx.series.started.items():
                for number, row in self.series_rows.get(name, ()):
                    if number > read_up_to and not self._blocked(row, ctx):
                        ctx.next_rows[name] = row
                        if name in ctx.series.liked:
                            ctx.score[row] += p.series_boost
                        break
        return ctx

    def _blocked(self, row: int, ctx: _Context) -> str | None:
        """Why `row` can't be picked at all right now, or None."""
        book = self.books[row]
        if self.excluded[row]:
            return self.excluded[row]
        if book.id in ctx.shelved_ids:
            return "on_shelf"
        if book.key in ctx.shelved_keys or book.key[0] in ctx.shelved_titles:
            return "copy_on_shelf"
        if book.key in ctx.picked_keys:
            return "copy_picked"
        return None

    def picks(
        self, shelf: list[ShelfItem], dnf_weights: dict[str, float], limit: int | None = None
    ) -> list[Pick]:
        """The reader's top picks, best first. Empty without any liked book that has text."""
        p = self.params
        limit = limit or p.picks
        ctx = self._context(shelf, dnf_weights)
        if ctx is None:
            return []
        chosen: list[Pick] = []
        for r in np.argsort(-ctx.score, kind="stable"):
            if self._blocked(r, ctx):
                continue
            target, _ = self._series_target(r, ctx)
            if target is None:
                continue
            book = self.books[target]
            if any(ctx.per_author[a] >= p.author_cap for a in book.authors):
                continue
            ctx.per_author.update(book.authors)
            ctx.picked_keys.add(book.key)
            because = ctx.liked_rows[int(np.argmax(ctx.sims[r]))]
            chosen.append(Pick(book.id, float(ctx.score[r]), self.books[because].id))
            if len(chosen) >= limit:
                break
        return chosen

    def _series_target(self, row: int, ctx: _Context) -> tuple[int | None, str]:
        """(row to recommend for `row`, or None to skip it; the rule that decided)."""
        p = self.params
        name, number = self.series[row]
        number = number or 0
        if not name:
            return row, ""
        if name == UNKNOWN_SERIES:
            # Can't tell if the reader has started it.
            return (row, "") if number <= 1 else (None, "book_n_skip")
        if name in ctx.series.dnf:
            return None, "dnf_series"
        if name in ctx.series.started and p.next_in_series:
            nxt = ctx.next_rows.get(name)
            if nxt is None or self._blocked(nxt, ctx):
                return None, "not_next_in_series"  # nothing unread left, or already picked
            if number > (self.series[nxt][1] or 0):
                return nxt, "not_next_in_series"
            return row, ""
        if name in ctx.series.started or number <= 1:
            return row, ""
        for first_number, first in self.series_rows.get(name, ()):
            if first_number > 1:
                return None, "series_first_book_missing"
            blocked = self._blocked(first, ctx)
            if not blocked:
                return first, "series_first_book_instead"
            if blocked == "copy_picked":
                return None, "series_first_book_instead"  # book 1 is already a pick
        return None, "series_first_book_missing"

    def explain(
        self, shelf: list[ShelfItem], dnf_weights: dict[str, float], book_id: int, depth: int
    ) -> str:
        """Why `book_id` isn't among the top `depth` picks for `shelf`: the first rule that
        stopped it, or "ranked_below" when nothing did and it simply scored too low."""
        if book_id not in self.row:
            return "no_text"
        ctx = self._context(shelf, dnf_weights)
        if ctx is None:
            return "no_liked_books"
        row = self.row[book_id]
        top: list[Pick] = []
        for pick in self.picks(shelf, dnf_weights, limit=depth):
            pr = self.row[pick.book_id]
            ctx.picked_keys.add(self.books[pr].key)
            ctx.per_author.update(self.books[pr].authors)
            top.append(pick)
        if any(pick.book_id == book_id for pick in top):
            return "picked"
        ctx.picked_keys.discard(self.books[row].key)  # its own key isn't a reason
        if reason := self._blocked(row, ctx):
            return reason
        target, rule = self._series_target(row, ctx)
        if target != row:
            return rule
        if any(ctx.per_author[a] >= self.params.author_cap for a in self.books[row].authors):
            return "author_cap"
        return "ranked_below"

    # --- More like this ------------------------------------------------------------

    def neighbours(self, chunk: int = 1000) -> dict[int, list[tuple[int, float]]]:
        """{book id: [(similar id, score)], best first} for every book with text."""
        k = self.params.neighbours
        extra = k + 15  # room to skip the book itself, copies of it and excluded books
        result: dict[int, list[tuple[int, float]]] = {}
        n = len(self.books)
        for start in range(0, n, chunk):
            sims = (self.matrix[start : start + chunk] @ self.matrix.T).toarray()
            take = min(extra, n)
            candidates = np.argpartition(-sims, take - 1, axis=1)[:, :take]
            for offset, row_candidates in enumerate(candidates):
                r = start + offset
                ranked = sorted(row_candidates, key=lambda c: -sims[offset, c])
                found = []
                for c in ranked:
                    if c == r or self.keys[c] == self.keys[r] or sims[offset, c] <= 0:
                        continue
                    if self.excluded[c]:
                        continue  # never show a box set, non-book or non-English work
                    found.append((self.books[c].id, float(sims[offset, c])))
                    if len(found) >= k:
                        break
                result[self.books[r].id] = found
        return result


# --- Held-out check (recommendation_profiles_report) ---------------------------------


@dataclass
class HoldoutResult:
    liked: int  # 4+ star books with text
    hidden: int  # targets per seed
    hits: dict[int, list[int]] = field(default_factory=dict)  # k -> hits per seed
    candidates: int = 0  # books that could be picked
    # Why targets missed the top max(k), summed over seeds ("ranked_below": scored too low).
    misses: Counter = field(default_factory=Counter)
    tail_hidden: list[int] = field(default_factory=list)  # extra series books hidden per seed

    def average(self, k: int) -> float:
        return sum(self.hits[k]) / len(self.hits[k]) if self.hits.get(k) else 0.0

    def rate(self, k: int) -> float:
        return self.average(k) / self.hidden if self.hidden else 0.0

    def random_rate(self, k: int) -> float:
        """Expected hit rate if the picks were random unread books."""
        return min(k, self.candidates) / self.candidates if self.candidates else 0.0


def holdout(
    model: Model,
    shelf: list[ShelfItem],
    dnf_weights: dict[str, float],
    seeds: list[int],
    fraction: float = 0.2,
    at: tuple[int, ...] = (20, 50),
    series_tails: bool = True,
) -> HoldoutResult:
    """Hide `fraction` of the 4+ star books (per seed), treat them as unread, and count how
    many come back in the top k picks.

    Series tails: hiding a series book also hides every later book of that series on the
    shelf (as unread, but not as a target), so the simulated reader is one a real reader
    could be: read up to just before the first hidden book. Hiding #2 and #3 while #4 stays
    read would be a reader the next-in-series rule rightly never recommends #2 to.
    """
    liked = [s for s in shelf if s.rating is not None and s.rating >= 4 and s.book_id in model.row]
    hidden_count = max(1, round(len(liked) * fraction)) if liked else 0
    result = HoldoutResult(liked=len(liked), hidden=hidden_count, hits={k: [] for k in at})
    if not hidden_count:
        return result
    depth = max(at)
    for seed in seeds:
        # A seeded sample for a repeatable evaluation, not security. (S311)
        targets = random.Random(seed).sample(liked, hidden_count)  # noqa: S311
        hidden_ids = {s.book_id for s in targets}
        tails = _series_tails(model, shelf, targets) - hidden_ids if series_tails else set()
        result.tail_hidden.append(len(tails))
        visible = [s for s in shelf if s.book_id not in hidden_ids | tails]
        result.candidates = len(model.books) - len(
            {s.book_id for s in visible if s.book_id in model.row}
        )
        picks = model.picks(visible, dnf_weights, limit=depth)
        picked_keys = [model.books[model.row[p.book_id]].key for p in picks]
        for k in at:
            keys = set(picked_keys[:k])
            result.hits[k].append(sum(1 for s in targets if s.key in keys))
        for target in targets:
            if target.key not in set(picked_keys):
                result.misses[model.explain(visible, dnf_weights, target.book_id, depth)] += 1
    return result


def _series_tails(model: Model, shelf: list[ShelfItem], targets: list[ShelfItem]) -> set[int]:
    """Shelf books later in the same series than a target (by effective series)."""
    first_hidden: dict[str, float] = {}
    for t in targets:
        name, number = model.shelf_series(t)
        if name and name != UNKNOWN_SERIES and number is not None:
            first_hidden[name] = min(first_hidden.get(name, number), number)
    tails = set()
    for s in shelf:
        name, number = model.shelf_series(s)
        if name in first_hidden and number is not None and number > first_hidden[name]:
            tails.add(s.book_id)
    return tails

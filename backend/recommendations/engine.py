"""TF-IDF recommendations (R-1, R-2, R-3, R-5): pure computation, no database access.

- Text per book: title, description and genres, each genre as one token (`genre_romance`)
  repeated `genre_weight` times (default 1: it beat 3 and 5 in the held-out check).
  English stop words removed; single words and two-word phrases ("slow burn", "found
  family") unless phrases=False. Rows are L2-normalized, so a dot
  product is cosine similarity.
- Personal picks (R-2): a candidate's score is the mean of its `top_liked` highest
  similarities to the reader's liked books (robust to mixed tastes, where one averaged
  profile would drift between them), minus the DNF penalty (R-5): the largest of
  weight(reason) x similarity over the reader's DNF books.
- Never recommended: anything on the shelf; another copy of a shelved book (same title +
  first author key, or the same title when the shelved copy has no author); box sets,
  non-books and non-English works (candidates.py). At most `author_cap` picks per author,
  counting every credited author.
- A later book in a series the reader hasn't started is replaced by the series' first book
  in the catalog (or skipped when there's none).
- Liked books: rated 4+ stars. With fewer than `min_liked`, also finished books rated 3+
  or unrated, and books being read now.
- More like this (R-3): each book's `neighbours` most similar books, never itself or
  another copy of itself.
"""

import random
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .candidates import exclusion_reason

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


@dataclass(frozen=True)
class ShelfItem:
    book_id: int
    status: str
    rating: int | None
    dnf_reason: str
    key: Key
    series: str = ""


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


class Model:
    """The TF-IDF matrix over every book with text."""

    def __init__(self, books: list[BookText], params: Params | None = None):
        params = params or Params()
        self.params = params
        self.books = [b for b in books if has_text(b)]
        self.row = {b.id: i for i, b in enumerate(self.books)}
        self.keys = [b.key for b in self.books]
        # Why each book can't be recommended (None: it can).
        self.excluded = [exclusion_reason(b.title, b.description, b.genres) for b in self.books]
        # series -> [(number, row)], first book first, for replacing mid-series picks.
        self.series_rows: dict[str, list[tuple[float, int]]] = {}
        for r, b in enumerate(self.books):
            if b.series and b.series_number is not None and not self.excluded[r]:
                self.series_rows.setdefault(b.series, []).append((b.series_number, r))
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

    def picks(
        self, shelf: list[ShelfItem], dnf_weights: dict[str, float], limit: int | None = None
    ) -> list[Pick]:
        """The reader's top picks, best first. Empty without any liked book that has text."""
        p = self.params
        limit = limit or p.picks
        liked_rows = self._rows(s.book_id for s in liked_books(shelf, p.min_liked))
        if not liked_rows:
            return []
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

        shelved_ids = {s.book_id for s in shelf}
        shelved_keys = {s.key for s in shelf}
        # A shelved copy with no author can only be recognised by its title.
        shelved_titles = {s.key[0] for s in shelf if title_only(s.key)}
        started_series = {s.series for s in shelf if s.series}
        order = np.argsort(-score, kind="stable")
        chosen: list[Pick] = []
        per_author: dict[str, int] = {}
        picked_keys: set[Key] = set()

        def blocked(row: int) -> bool:
            book = self.books[row]
            return bool(
                self.excluded[row]
                or book.id in shelved_ids
                or book.key in shelved_keys
                or book.key in picked_keys
                or book.key[0] in shelved_titles
            )

        for r in order:
            if blocked(r):
                continue
            target = self._series_start(r, started_series, blocked)
            if target is None:
                continue
            book = self.books[target]
            if any(per_author.get(a, 0) >= p.author_cap for a in book.authors):
                continue
            for a in book.authors:
                per_author[a] = per_author.get(a, 0) + 1
            picked_keys.add(book.key)
            because = liked_rows[int(np.argmax(sims[r]))]
            chosen.append(Pick(book.id, float(score[r]), self.books[because].id))
            if len(chosen) >= limit:
                break
        return chosen

    def _series_start(self, row: int, started: set[str], blocked) -> int | None:
        """The row to recommend for `row`: itself, unless it's a later book in a series the
        reader hasn't started; then that series' first available book, or None."""
        book = self.books[row]
        if not book.series or (book.series_number or 0) <= 1 or book.series in started:
            return row
        for number, first in self.series_rows.get(book.series, ()):
            if number > 1:
                return None  # the series' first book isn't in the catalog
            if not blocked(first):
                return first
        return None

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
    hidden: int  # per seed
    hits: dict[int, list[int]] = field(default_factory=dict)  # k -> hits per seed
    candidates: int = 0  # books that could be picked

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
) -> HoldoutResult:
    """Hide `fraction` of the 4+ star books (per seed), treat them as unread, and count how
    many come back in the top k picks."""
    liked = [s for s in shelf if s.rating is not None and s.rating >= 4 and s.book_id in model.row]
    hidden_count = max(1, round(len(liked) * fraction)) if liked else 0
    result = HoldoutResult(liked=len(liked), hidden=hidden_count, hits={k: [] for k in at})
    if not hidden_count:
        return result
    for seed in seeds:
        # A seeded sample for a repeatable evaluation, not security. (S311)
        hidden = random.Random(seed).sample(liked, hidden_count)  # noqa: S311
        hidden_ids = {s.book_id for s in hidden}
        visible = [s for s in shelf if s.book_id not in hidden_ids]
        result.candidates = len(model.books) - len(
            {s.book_id for s in visible if s.book_id in model.row}
        )
        picks = model.picks(visible, dnf_weights, limit=max(at))
        hidden_keys = {s.key for s in hidden}
        for k in at:
            result.hits[k].append(
                sum(1 for p in picks[:k] if model.books[model.row[p.book_id]].key in hidden_keys)
            )
    return result

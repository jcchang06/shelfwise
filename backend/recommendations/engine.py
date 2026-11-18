"""TF-IDF recommendations (R-1, R-2, R-3, R-5): pure computation, no database access.

- Text per book: title, description and genres, each genre as one token (`genre_romance`)
  repeated `genre_weight` times so a shared genre weighs about as much as a few shared
  description words. English stop words removed; single words and two-word phrases
  ("slow burn", "found family") unless phrases=False. Rows are L2-normalized, so a dot
  product is cosine similarity.
- Personal picks (R-2): a candidate's score is the mean of its `top_liked` highest
  similarities to the reader's liked books (robust to mixed tastes, where one averaged
  profile would drift between them), minus the DNF penalty (R-5): the largest of
  weight(reason) x similarity over the reader's DNF books. Never recommended: anything on
  the shelf, or another copy of a shelved book (same title + first author key). At most
  `author_cap` picks per author.
- Liked books: rated 4+ stars. With fewer than `min_liked`, also finished books rated 3+
  or unrated, and books being read now.
- More like this (R-3): each book's `neighbours` most similar books, never itself or
  another copy of itself.
"""

import random
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

Key = tuple[str, str]  # normalize.title_author_key(title, first author)


@dataclass(frozen=True)
class BookText:
    id: int
    title: str
    description: str
    genres: tuple[str, ...]
    author: str  # normalized first author ("" if none), for the per-author cap
    key: Key


@dataclass(frozen=True)
class ShelfItem:
    book_id: int
    status: str
    rating: int | None
    dnf_reason: str
    key: Key


@dataclass(frozen=True)
class Params:
    genre_weight: int = 3
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
        order = np.argsort(-score, kind="stable")
        chosen: list[Pick] = []
        per_author: dict[str, int] = {}
        picked_keys: set[Key] = set()
        for r in order:
            book = self.books[r]
            if book.id in shelved_ids or book.key in shelved_keys or book.key in picked_keys:
                continue
            if book.author and per_author.get(book.author, 0) >= p.author_cap:
                continue
            per_author[book.author] = per_author.get(book.author, 0) + 1
            picked_keys.add(book.key)
            because = liked_rows[int(np.argmax(sims[r]))]
            chosen.append(Pick(book.id, float(score[r]), self.books[because].id))
            if len(chosen) >= limit:
                break
        return chosen

    def neighbours(self, chunk: int = 1000) -> dict[int, list[tuple[int, float]]]:
        """{book id: [(similar id, score)], best first} for every book with text."""
        k = self.params.neighbours
        extra = k + 5  # room to skip the book itself and other copies of it
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

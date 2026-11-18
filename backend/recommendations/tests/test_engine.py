"""The TF-IDF engine (R-1, R-2, R-3, R-5), on small hand-made catalogs."""

import pytest

from recommendations.engine import BookText, Model, Params, ShelfItem, holdout, liked_books

WEIGHTS = {"writing_style": 1.0, "pacing": 0.5, "not_in_the_mood": 0.0, "not_specified": 0.0}


def book(n, words, genres=(), author=None, key=None):
    author = author if author is not None else f"author {n}"
    return BookText(n, f"Book {n}", words, tuple(genres), author, key or (f"book {n}", author))


def shelved(b: BookText, status="finished", rating=5, reason=""):
    return ShelfItem(b.id, status, rating, reason, b.key)


DRAGONS = "dragons magic kingdom quest sword wizard"
SPACE = "spaceship galaxy alien planet starship crew"
LOVE = "romance love wedding kiss heart summer"


@pytest.fixture
def catalog():
    books = []
    n = 0
    for theme, genre in ((DRAGONS, "Fantasy"), (SPACE, "Science Fiction"), (LOVE, "Romance")):
        for variant in range(6):
            n += 1
            books.append(book(n, f"{theme} story{variant} chapter{variant % 2}", [genre]))
    return books


def ids(picks):
    return [p.book_id for p in picks]


class TestModel:
    def test_books_without_text_are_left_out(self, catalog):
        model = Model([*catalog, book(99, "", ())])
        assert 99 not in model.row and len(model.books) == len(catalog)

    def test_picks_follow_liked_books_and_never_include_the_shelf(self, catalog):
        model = Model(catalog)
        shelf = [shelved(catalog[0]), shelved(catalog[1])]  # two dragon books
        picks = model.picks(shelf, WEIGHTS, limit=4)
        assert set(ids(picks)) <= {b.id for b in catalog[2:6]}  # the other dragon books
        assert picks[0].because_of in {catalog[0].id, catalog[1].id}

    def test_mixed_tastes_get_both(self, catalog):
        model = Model(catalog, Params(author_cap=10))
        shelf = [shelved(catalog[0]), shelved(catalog[12])]  # one dragon, one romance
        top = set(ids(model.picks(shelf, WEIGHTS, limit=6)))
        assert top & {b.id for b in catalog[1:6]} and top & {b.id for b in catalog[13:18]}

    def test_a_dnf_pushes_similar_books_down_by_its_reason(self, catalog):
        model = Model(catalog, Params(author_cap=10))
        liked = [shelved(catalog[0]), shelved(catalog[12])]  # dragons and romance
        romance = {b.id for b in catalog[13:18]}
        baseline = ids(model.picks(liked, WEIGHTS, limit=4))
        disliked = [*liked, shelved(catalog[18 - 1], "dnf", None, "writing_style")]
        penalised = ids(model.picks(disliked, WEIGHTS, limit=4))
        assert len(set(penalised) & romance) < len(set(baseline) & romance)
        # "not in the mood" has weight 0: the same picks as shelving it with no penalty.
        mood = [*liked, shelved(catalog[17], "dnf", None, "not_in_the_mood")]
        neutral = [*liked, shelved(catalog[17], "want_to_read", None)]
        assert ids(model.picks(mood, WEIGHTS, limit=4)) == ids(
            model.picks(neutral, WEIGHTS, limit=4)
        )

    def test_another_copy_of_a_shelved_book_is_never_picked(self, catalog):
        copy = book(50, DRAGONS + " story0 chapter0", ["Fantasy"], key=catalog[0].key)
        model = Model([*catalog, copy])
        assert 50 not in ids(model.picks([shelved(catalog[0])], WEIGHTS))

    def test_at_most_two_picks_per_author(self, catalog):
        same_author = [
            book(60 + i, DRAGONS + f" extra{i}", ["Fantasy"], author="prolific") for i in range(5)
        ]
        model = Model([*catalog, *same_author])
        picks = model.picks([shelved(catalog[0])], WEIGHTS, limit=10)
        assert sum(1 for p in picks if p.book_id >= 60) <= 2

    def test_no_liked_books_no_picks(self, catalog):
        model = Model(catalog)
        assert model.picks([], WEIGHTS) == []
        assert model.picks([shelved(catalog[0], "want_to_read", None)], WEIGHTS) == []

    def test_neighbours_skip_the_book_itself_and_its_copies(self, catalog):
        copy = book(50, DRAGONS + " story0 chapter0", ["Fantasy"], key=catalog[0].key)
        model = Model([*catalog, copy], Params(neighbours=3))
        found = model.neighbours(chunk=4)  # several chunks
        first = [similar for similar, _ in found[catalog[0].id]]
        assert catalog[0].id not in first and 50 not in first
        assert set(first) <= {b.id for b in catalog[1:6]}
        assert len(found) == len(model.books)

    def test_genre_weight_and_phrases_change_the_vocabulary(self, catalog):
        assert Model(catalog, Params(phrases=False)).vocabulary < Model(catalog).vocabulary


class TestLikedBooks:
    def test_four_stars_and_up(self, catalog):
        shelf = [shelved(b, rating=r) for b, r in zip(catalog[:6], (5, 4, 4, 5, 4, 3), strict=True)]
        assert len(liked_books(shelf, min_liked=5)) == 5

    def test_too_few_also_counts_finished_3_or_unrated_and_reading(self, catalog):
        shelf = [
            shelved(catalog[0], rating=5),
            shelved(catalog[1], rating=3),
            shelved(catalog[2], rating=None),
            shelved(catalog[3], "reading", None),
            shelved(catalog[4], rating=2),  # disliked
            shelved(catalog[5], "want_to_read", None),
        ]
        assert {s.book_id for s in liked_books(shelf, min_liked=5)} == {
            catalog[0].id,
            catalog[1].id,
            catalog[2].id,
            catalog[3].id,
        }


class TestHoldout:
    def test_hidden_liked_books_come_back_in_the_picks(self, catalog):
        model = Model(catalog, Params(author_cap=10))
        shelf = [shelved(b) for b in catalog[:5]]  # five dragon books
        result = holdout(model, shelf, WEIGHTS, seeds=[0, 1, 2], fraction=0.2, at=(3, 10))
        assert result.liked == 5 and result.hidden == 1
        assert result.hits[10] == [1, 1, 1]  # the hidden dragon book is always found
        assert result.rate(10) == 1.0
        assert 0 < result.random_rate(3) < 1

    def test_the_same_seed_hides_the_same_books(self, catalog):
        model = Model(catalog)
        shelf = [shelved(b) for b in catalog[:10]]
        a = holdout(model, shelf, WEIGHTS, seeds=[4])
        b = holdout(model, shelf, WEIGHTS, seeds=[4])
        assert a.hits == b.hits

    def test_no_liked_books(self, catalog):
        result = holdout(Model(catalog), [], WEIGHTS, seeds=[0])
        assert result.hidden == 0 and result.rate(20) == 0.0

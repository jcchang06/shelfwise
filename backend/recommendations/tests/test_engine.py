"""The TF-IDF engine (R-1, R-2, R-3, R-5), on small hand-made catalogs."""

import pytest

from recommendations.engine import (
    NO_AUTHOR,
    BookText,
    Model,
    Params,
    ShelfItem,
    holdout,
    liked_books,
)

WEIGHTS = {"writing_style": 1.0, "pacing": 0.5, "not_in_the_mood": 0.0, "not_specified": 0.0}


def book(
    n, words, genres=(), author=None, key=None, title=None, authors=None, series="", number=None
):
    author = author if author is not None else f"author {n}"
    title = title or f"Book {n}"
    return BookText(
        n,
        title,
        words,
        tuple(genres),
        tuple(authors) if authors is not None else (author,),
        key or (title.casefold(), author),
        series,
        number,
    )


def shelved(b: BookText, status="finished", rating=5, reason=""):
    return ShelfItem(b.id, status, rating, reason, b.key, b.series, b.series_number)


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

    def test_genre_weight_defaults_to_1_and_0_leaves_genres_out(self, catalog):
        assert Params().genre_weight == 1
        assert "genre_fantasy" not in Model(catalog, Params(genre_weight=0)).vectorizer.vocabulary_


class TestCandidateFixes:
    """The six issues found in the first real picks (Nov 17, 2026)."""

    def test_box_sets_are_never_picked_or_shown_as_similar(self, catalog):
        box = book(
            70, DRAGONS + " story1 chapter1 story2", ["Fantasy"], title="Book 2 / Book 3 / Book 4"
        )
        series = book(
            71, DRAGONS + " story3 chapter1", ["Fantasy"], title="Dragon Saga (series) 1-7"
        )
        model = Model([*catalog, box, series], Params(author_cap=10))
        picks = ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))
        assert 70 not in picks and 71 not in picks
        similar = [s for s, _ in model.neighbours()[catalog[0].id]]
        assert 70 not in similar and 71 not in similar

    def test_a_shelved_copy_with_no_author_still_blocks_its_title(self, catalog):
        # The live case: the library copy had no linked author, the seeded one did.
        library = book(
            80,
            DRAGONS + " story0 chapter0",
            ["Fantasy"],
            title="Shadow and Bone",
            authors=(),
            key=("shadow and bone", f"{NO_AUTHOR}80"),
        )
        seeded = book(
            81,
            DRAGONS + " story0 chapter0",
            ["Fantasy"],
            title="Shadow and Bone",
            author="leigh bardugo",
            key=("shadow and bone", "leigh bardugo"),
        )
        model = Model([*catalog, library, seeded])
        assert 81 not in ids(model.picks([shelved(library)], WEIGHTS, limit=20))

    def test_non_books_and_fan_fiction_are_never_picked(self, catalog):
        poster = book(90, DRAGONS + " story0 chapter1", ["Fantasy"], title="The Dragon Poster Book")
        fanfic = book(
            91,
            DRAGONS + " story1 chapter0",
            ["Fantasy", "Fan fiction"],
            title="Dragons and the Methods",
        )
        model = Model([*catalog, poster, fanfic], Params(author_cap=10))
        picks = ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))
        assert 90 not in picks and 91 not in picks

    def test_works_with_a_non_english_title_are_never_picked(self, catalog):
        german = book(
            95, DRAGONS + " story2 chapter0", ["Fantasy"], title="Die Stadt der Träumenden Bücher"
        )
        model = Model([*catalog, german], Params(author_cap=10))
        assert 95 not in ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))

    def test_the_author_cap_counts_every_credited_author(self, catalog):
        rowling = [
            book(
                100 + i,
                DRAGONS + f" wand{i}",
                ["Fantasy"],
                authors=(f"illustrator {i}", "jk rowling"),
            )
            for i in range(5)
        ]
        model = Model([*catalog, *rowling], Params(author_cap=2))
        picks = ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))
        assert sum(1 for p in picks if p >= 100) == 2

    def test_a_later_book_of_an_unstarted_series_becomes_its_first_book(self, catalog):
        first = book(
            110, SPACE + " detective one", ["Science Fiction"], series="dresden files", number=1.0
        )
        seventh = book(
            111,
            DRAGONS + " story0 chapter0 wizard",
            ["Fantasy"],
            series="dresden files",
            number=7.0,
        )
        model = Model([*catalog, first, seventh], Params(author_cap=10))
        picks = ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))
        assert 111 not in picks and 110 in picks
        assert picks.index(110) < 3  # it takes the place where book 7 scored

    def test_a_later_book_is_fine_once_the_series_is_started(self, catalog):
        first = book(
            110, SPACE + " detective one", ["Science Fiction"], series="dresden files", number=1.0
        )
        seventh = book(
            111,
            DRAGONS + " story0 chapter0 wizard",
            ["Fantasy"],
            series="dresden files",
            number=7.0,
        )
        model = Model([*catalog, first, seventh], Params(author_cap=10))
        assert 111 in ids(model.picks([shelved(catalog[0]), shelved(first)], WEIGHTS, limit=20))

    def test_without_the_first_book_in_the_catalog_a_later_one_is_skipped(self, catalog):
        seventh = book(
            111,
            DRAGONS + " story0 chapter0 wizard",
            ["Fantasy"],
            series="dresden files",
            number=7.0,
        )
        model = Model([*catalog, seventh], Params(author_cap=10))
        assert 111 not in ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))


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


class TestNextInSeries:
    """R-6 and the follow-up misses: next unread in a started series, DNF'd series,
    unknown series."""

    def crescent(self):
        return [
            book(
                200 + n,
                f"{DRAGONS} crescent city bryce story{n}",
                ["Fantasy"],
                title=f"House {n}",
                author="sarah j maas",
                series="crescent city",
                number=float(n),
            )
            for n in (1, 2, 3)
        ]

    def test_after_book_1_the_next_pick_is_book_2_not_book_3(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10))
        picks = ids(model.picks([shelved(one)], WEIGHTS, limit=20))
        assert two.id in picks and three.id not in picks

    def test_the_next_book_is_boosted_when_the_last_was_liked(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10))
        boosted = model.picks([shelved(one, rating=5)], WEIGHTS, limit=20)
        plain = Model([*catalog, one, two, three], Params(author_cap=10, series_boost=0))
        flat = plain.picks([shelved(one, rating=5)], WEIGHTS, limit=20)
        score = {p.book_id: p.score for p in boosted}
        flat_score = {p.book_id: p.score for p in flat}
        assert score[two.id] == pytest.approx(flat_score[two.id] + Params().series_boost)

    def test_no_boost_when_the_finished_book_was_disliked(self, catalog):
        one, two, three = self.crescent()
        boost = Model([*catalog, one, two, three], Params(author_cap=10))
        flat = Model([*catalog, one, two, three], Params(author_cap=10, series_boost=0))
        a = {
            p.book_id: p.score
            for p in boost.picks([shelved(one, rating=2), shelved(catalog[0])], WEIGHTS, limit=20)
        }
        b = {
            p.book_id: p.score
            for p in flat.picks([shelved(one, rating=2), shelved(catalog[0])], WEIGHTS, limit=20)
        }
        assert two.id in a  # still the next pick, just not boosted
        assert a[two.id] == pytest.approx(b[two.id])

    def test_after_books_1_and_2_the_next_is_3(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10))
        assert three.id in ids(model.picks([shelved(one), shelved(two)], WEIGHTS, limit=20))

    def test_a_series_with_a_dnf_is_skipped(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10))
        picks = ids(
            model.picks(
                [shelved(catalog[0]), shelved(one, "dnf", None, "pacing")], WEIGHTS, limit=20
            )
        )
        assert two.id not in picks and three.id not in picks

    def test_a_numbered_book_in_an_unknown_series(self, catalog):
        later = book(
            300,
            DRAGONS + " story0 chapter0",
            ["Fantasy"],
            title="Apprentice #10",
            series="?",
            number=10.0,
        )
        first = book(
            301,
            DRAGONS + " story1 chapter1",
            ["Fantasy"],
            title="Apprentice #1",
            series="?",
            number=1.0,
        )
        model = Model([*catalog, later, first], Params(author_cap=10))
        picks = ids(model.picks([shelved(catalog[0])], WEIGHTS, limit=20))
        assert later.id not in picks and first.id in picks


class TestDiagnosis:
    """Miss reasons, rule switches and the series-tail simulation (held-out diagnosis)."""

    def series_books(self):
        return [
            book(
                400 + n,
                f"{DRAGONS} saga part story{n}",
                ["Fantasy"],
                title=f"Saga {n}",
                author=f"saga author {n}",
                series="saga",
                number=float(n),
                key=(f"saga {n}", "x"),
            )
            for n in range(1, 5)
        ]

    def test_explain_names_the_rule_that_stopped_a_book(self, catalog):
        one, two, three, four = self.series_books()
        model = Model([*catalog, one, two, three, four], Params(author_cap=10))
        # Read #1 and #4: #2 and #3 can't be "next" (the impossible reader).
        shelf = [shelved(one), shelved(four), shelved(catalog[0])]
        assert model.explain(shelf, WEIGHTS, three.id, depth=20) == "not_next_in_series"
        assert model.explain(shelf, WEIGHTS, catalog[0].id, depth=20) == "on_shelf"
        assert model.explain(shelf, WEIGHTS, 999, depth=20) == "no_text"

    def test_explain_excluded_and_ranked_below(self, catalog):
        poster = book(90, DRAGONS + " story0", ["Fantasy"], title="The Dragon Poster Book")
        model = Model([*catalog, poster], Params(author_cap=10))
        shelf = [shelved(catalog[0])]
        assert model.explain(shelf, WEIGHTS, 90, depth=20) == "not_a_book"
        assert model.explain(shelf, WEIGHTS, catalog[12].id, depth=1) == "ranked_below"

    def test_rule_switches(self, catalog):
        poster = book(
            90, DRAGONS + " story0", ["Fantasy", "Picture books"], title="Dragons", number=None
        )
        model = Model([*catalog, poster], Params(picture_books=False, author_cap=10))
        assert model.excluded[model.row[90]] is None
        cued = book(91, DRAGONS + " story1", ["Fantasy"], title="Saga X", series="saga", number=5.0)
        cued = BookText(**{**cued.__dict__, "series_source": "description"})
        off = Model([*catalog, cued], Params(description_series=False))
        assert off.series[off.row[91]] == ("", None)
        one, two, three, four = self.series_books()
        free = Model([*catalog, one, two, three, four], Params(next_in_series=False, author_cap=10))
        shelf = [shelved(one), shelved(four), shelved(catalog[0])]
        assert {two.id, three.id} <= set(ids(free.picks(shelf, WEIGHTS, limit=30)))

    def test_holdout_hides_series_tails_and_reports_misses(self, catalog):
        one, two, three, four = self.series_books()
        model = Model([*catalog, one, two, three, four], Params(author_cap=10))
        shelf = [shelved(b) for b in (one, two, three, four, *catalog[:6])]
        tails = holdout(model, shelf, WEIGHTS, seeds=list(range(6)), fraction=0.2)
        random_only = holdout(
            model, shelf, WEIGHTS, seeds=list(range(6)), fraction=0.2, series_tails=False
        )
        assert sum(tails.tail_hidden) > 0 and random_only.tail_hidden == [0] * 6
        assert sum(tails.misses.values()) + sum(tails.hits[50]) == tails.hidden * 6

    def test_series_tails_leave_a_reader_who_could_exist(self, catalog):
        from recommendations.engine import _series_tails

        one, two, three, four = self.series_books()
        model = Model([*catalog, one, two, three, four])
        shelf = [shelved(b) for b in (one, two, three, four)]
        # Hiding #2 also hides #3 and #4: the reader has read #1 only.
        assert _series_tails(model, shelf, [shelved(two)]) == {three.id, four.id}
        assert _series_tails(model, shelf, [shelved(four)]) == set()


class TestBoostEffect:
    def crescent(self):
        return [
            book(
                500 + n,
                f"{SPACE} crescent saga story{n}",
                ["Science Fiction"],
                title=f"House {n}",
                author=f"maas {n}",
                series="crescent city",
                number=float(n),
                key=(f"house {n}", "m"),
            )
            for n in (1, 2, 3)
        ]

    def test_the_boost_is_applied_and_measured(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10, series_boost=0.5))
        shelf = [shelved(one), shelved(catalog[0]), shelved(catalog[1])]
        effect = model.boost_effect(shelf, WEIGHTS, depth=5)
        assert effect.boosted == 1 and effect.in_top == 1
        plain = ids(model.picks(shelf, WEIGHTS, limit=5, boost=False))
        boosted = ids(model.picks(shelf, WEIGHTS, limit=5))
        assert boosted.index(two.id) < (plain.index(two.id) if two.id in plain else 99)

    def test_no_boost_no_effect(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10, series_boost=0))
        effect = model.boost_effect([shelved(one), shelved(catalog[0])], WEIGHTS, depth=5)
        assert (effect.boosted, effect.moved, effect.entered, effect.left) == (0, 0, 0, 0)

    def test_holdout_reports_the_boost(self, catalog):
        one, two, three = self.crescent()
        model = Model([*catalog, one, two, three], Params(author_cap=10))
        shelf = [shelved(b) for b in (one, two, three, *catalog[:7])]
        result = holdout(model, shelf, WEIGHTS, seeds=[0, 1, 2])
        assert len(result.boost) == 3 and set(result.hits_from_boost) == {20, 50}

"""Candidate rules (candidates.py), on the real titles that prompted them."""

import pytest

from recommendations import candidates


@pytest.mark.parametrize(
    "title",
    [
        "A Court of Thorns and Roses / A Court of Mist and Fury / A Court of Wings and Ruin",
        "Harry Potter (series) 1-7",
        "All Creatures Great and Small (All Creatures Great and Small #1-2)",
        "The Hunger Games Box Set",
        "Bram Stoker's Dracula omnibus",
        "The Lord of the Rings Trilogy",
        "Books 1-3 of the Wheel",
    ],
)
def test_omnibus(title):
    assert candidates.is_omnibus(title)


@pytest.mark.parametrize(
    "title",
    [
        "9-11",
        "Shadow and Bone",
        "Six of Crows",
        "11/22/63",
        "Reached (Matched Trilogy, Book 3)",
        "Star Wars - Thrawn Trilogy - Heir to the Empire",
    ],
)
def test_not_omnibus(title):
    assert not candidates.is_omnibus(title)


@pytest.mark.parametrize(
    ("title", "genres", "expected"),
    [
        ("Harry Potter Poster Book", (), True),
        ("The Secret Garden Coloring Book", (), True),
        ("Outlander 2027 Calendar", (), True),
        ("The Official Harry Potter Companion", (), True),
        ("Harry Potter and the Methods of Rationality", ("Fan fiction",), True),
        ("A Good Girl's Guide to Murder", (), False),
        ("The Notebook", (), False),
        ("The Outlander Companion", (), True),
    ],
)
def test_not_a_book(title, genres, expected):
    assert candidates.is_not_a_book(title, genres) is expected


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Der Vorleser", "", True),
        ("Die Stadt der Träumenden Bücher", "", True),
        ("Cien años de soledad", "", True),
        ("Fear and Loathing in Las Vegas", "", False),
        ("In Search of Schrödinger's Cat", "", False),
        ("The massacre at El Mozote", "", False),
        ("Die Trying", "", False),  # English: "die" alone is not a cue
        (
            "2666",
            "La novela de la que todos hablan, con una historia que es para los lectores " * 2,
            True,
        ),
    ],
)
def test_foreign(title, description, expected):
    assert candidates.is_foreign(title, description) is expected


@pytest.mark.parametrize(
    ("title", "series_name", "number", "expected"),
    [
        ("Dead Beat (The Dresden Files, Book 7)", "", None, ("dresden files", 7.0)),
        ("A Living Nightmare (Cirque Du Freak #1)", "", None, ("cirque du freak", 1.0)),
        ("Shadow and Bone", "The Shadow and Bone Trilogy", 1, ("shadow and bone trilogy", 1.0)),
        ("Shadow and Bone", "", None, ("", None)),
    ],
)
def test_series_of(title, series_name, number, expected):
    assert candidates.series_of(title, series_name, number) == expected


# --- Follow-up rules (Nov 18, 2026) ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("密やかな結晶", True),
        ("Анна Каренина", True),
        ("Φαίδων", True),
        ("Les Misérables", False),
        ("Pokémon Adventures", False),
    ],
)
def test_non_latin(title, expected):
    assert candidates.is_non_latin(title) is expected


def test_marker_only_title():
    assert candidates.is_marker_only("(Airhead #1)")
    assert not candidates.is_marker_only("Airhead (Airhead #1)")


@pytest.mark.parametrize(
    ("genres", "pages", "expected"),
    [
        (("Juvenile fiction", "Stories in rhyme"), 48, True),  # Bartholomew and the Oobleck
        (("Picture books",), 40, True),
        (("Picture books",), None, True),
        (
            ("Picture books for children", "Juvenile"),
            175,
            False,
        ),  # Charlie and the Chocolate Factory
        (("Juvenile fiction",), 40, True),
        (("Juvenile fiction",), 350, False),  # a middle-grade novel
        (("Juvenile fiction",), 1, False),  # an implausible count: treated as unknown
        (("Fantasy",), 40, False),  # short, but not juvenile
        (("Juvenile fiction",), None, False),
    ],
)
def test_picture_book(genres, pages, expected):
    assert candidates.is_picture_book(genres, pages) is expected


def test_exclusion_reasons_for_the_reported_misses():
    assert candidates.exclusion_reason("(Airhead #1)", "", ()) == "marker_only"
    assert candidates.exclusion_reason("密やかな結晶", "", ()) == "non_latin"
    assert (
        candidates.exclusion_reason(
            "Bartholomew and the oobleck", "", ("Juvenile fiction", "Stories in rhyme"), 48
        )
        == "picture_book"
    )


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        (
            "The stunning third book in the sexy, action-packed Crescent City series, following",
            ("crescent city", 3.0),
        ),
        ("sixth novel in Diana Gabaldon's bestselling Outlander saga", ("outlander", 6.0)),
        ("the second book in the NYT best-selling Expanse series", ("expanse", 2.0)),
        ("fourth installment of The Mortal Instruments series", ("mortal instruments", 4.0)),
        ("Book 10 in the Ranger's Apprentice series", ("ranger s apprentice", 10.0)),
        ("second novel in Nora Roberts's celebrated Bride Quartet series", ("bride quartet", 2.0)),
        ("her second novel, a story of love and loss", ("", None)),  # no named series
    ],
)
def test_series_from_description(description, expected):
    assert candidates.series_from_description(description) == expected


def test_series_sources_in_order():
    assert candidates.series_of(
        "House of Flame and Shadow", "", None, "third book in the Crescent City series"
    ) == ("crescent city", 3.0)
    assert candidates.series_of("Ranger's Apprentice #10", "", None) == (
        candidates.UNKNOWN_SERIES,
        10.0,
    )
    assert candidates.series_of("A Book", "Crescent City", 1, "third book in the Other series") == (
        "crescent city",
        1.0,
    )

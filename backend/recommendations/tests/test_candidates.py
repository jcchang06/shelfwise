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

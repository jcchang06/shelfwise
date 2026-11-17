"""Goodreads CSV parsing and field mapping (I-1). Uses only synthetic data."""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from imports.csv_parser import (
    REQUIRED_COLUMNS,
    ImportFileError,
    isbn10_to_13,
    map_row,
    map_status,
    parse_goodreads_csv,
    parse_isbn,
    split_series,
)
from tracking.models import UserBook

S = UserBook.Status
SAMPLE = Path(__file__).parent / "fixtures" / "synthetic_goodreads.csv"


@pytest.fixture
def rows():
    return {r.row_number: r for r in parse_goodreads_csv(SAMPLE.read_bytes())}


def csv_bytes(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode()


HEADER = ",".join(REQUIRED_COLUMNS)


class TestFile:
    def test_parses_the_sample_with_a_bom(self, rows):
        assert len(rows) == 12
        assert rows[1].goodreads_book_id == "9000001"  # BOM didn't corrupt the first column

    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (b"", "empty"),
            (b"   \n", "empty"),
            (b"\xff\xfe\x00\x00not utf8", "UTF-8"),
            (
                csv_bytes("Title,Author", "Dune,Frank Herbert"),
                "doesn't look like a Goodreads export",
            ),
            (csv_bytes(HEADER), "no books"),
        ],
    )
    def test_rejects_unusable_files(self, data, message):
        with pytest.raises(ImportFileError, match=message):
            parse_goodreads_csv(data)

    def test_missing_columns_are_named(self):
        header = ",".join(c for c in REQUIRED_COLUMNS if c not in ("ISBN13", "Date Read"))
        with pytest.raises(ImportFileError, match="missing columns: ISBN13, Date Read"):
            parse_goodreads_csv(csv_bytes(header, ""))

    def test_size_limit(self, settings):
        settings.IMPORT_MAX_FILE_BYTES = 100
        with pytest.raises(ImportFileError, match="too large"):
            parse_goodreads_csv(b"x" * 101)

    def test_row_limit(self, settings):
        settings.IMPORT_MAX_ROWS = 2
        lines = [HEADER] + [f"{i},Book {i},A,,,0,read,,," for i in range(3)]
        with pytest.raises(ImportFileError, match="more than 2 books"):
            parse_goodreads_csv(csv_bytes(*lines))

    def test_header_whitespace_is_tolerated(self):
        header = ", ".join(REQUIRED_COLUMNS)
        parsed = parse_goodreads_csv(csv_bytes(header, "1,Dune,Frank Herbert,,,0,read,,,"))
        assert parsed[0].title == "Dune"

    def test_quoted_commas_and_quotes(self, rows):
        assert rows[12].title == "Salt, Smoke & Silence"
        assert rows[12].author == 'Mira "Jo" Kestrel'

    def test_duplicate_book_id_keeps_the_first(self, rows):
        assert rows[1].error == ""
        assert rows[10].error == "Same Goodreads book as row 1; only the first is imported."

    def test_row_without_title_is_an_error_row(self, rows):
        assert rows[11].error == "This row has no Goodreads Book Id or title."

    def test_private_columns_are_not_kept(self, rows):
        assert "PRIVATE" not in repr(rows[1])  # Private Notes is never read


class TestFields:
    def test_full_row(self, rows):
        row = rows[1]
        assert row.title == "The Glass Orchard"
        assert (row.series_name, row.series_number) == ("Lanternfall", Decimal("1"))
        assert row.author == "Mara Vell"
        assert row.isbn_13 == "9780000000019"
        assert row.page_count == 412
        assert row.year_published == 2018  # original publication year wins
        assert row.status == S.FINISHED and row.rating == 5
        assert row.date_read == dt.date(2024, 3, 9) and row.date_added == dt.date(2024, 1, 2)
        assert row.review == "Loved it.\n\nSecond paragraph & more."
        assert row.notes == []

    def test_additional_authors(self, rows):
        assert rows[3].additional_authors == "Bram Sato, Lu Chen"

    def test_isbn10_is_converted(self, rows):
        assert rows[6].isbn_13 == isbn10_to_13("0000000027") == "9780000000026"

    def test_no_isbn(self, rows):
        assert rows[2].isbn_13 == ""

    def test_unreadable_date_is_noted(self, rows):
        assert rows[9].date_read is None
        assert "Couldn't read the date “sometime in 2019”." in rows[9].notes


class TestStatusAndRating:
    @pytest.mark.parametrize(
        ("row", "status"),
        [(1, S.FINISHED), (2, S.READING), (3, S.WANT_TO_READ), (4, S.DNF), (5, S.DNF)],
    )
    def test_shelf_mapping(self, rows, row, status):
        assert rows[row].status == status

    def test_dnf_shelf_wins_over_exclusive_shelf(self, rows):
        # Row 4 is on "read" but also the custom "dnf" shelf; row 5 is "Did-Not-Finish".
        assert rows[4].status == rows[5].status == S.DNF

    def test_unknown_exclusive_shelf(self, rows):
        assert rows[8].status == S.WANT_TO_READ
        assert rows[8].notes == ["Unknown shelf “abandoned” imported as Want to read."]

    def test_rating_dropped_unless_finished(self, rows):
        assert rows[3].rating is None
        assert rows[3].notes == [
            "Your 4★ rating wasn't imported: ratings need Finished, not Want to read."
        ]
        assert rows[4].rating is None  # DNF: stars and a DNF don't mix
        assert "ratings need Finished, not Did not finish" in rows[4].notes[0]

    def test_zero_rating_means_unrated(self, rows):
        assert rows[2].rating is None and rows[2].notes == []

    @pytest.mark.parametrize(
        ("exclusive", "shelves", "expected"),
        [
            ("read", "", S.FINISHED),
            ("READ", "", S.FINISHED),
            ("to-read", "DNF", S.DNF),
            ("currently-reading", "fantasy,  did-not-finish ", S.DNF),
            ("read", "dnf-maybe", S.FINISHED),  # only the exact shelf names count
        ],
    )
    def test_map_status(self, exclusive, shelves, expected):
        assert map_status(exclusive, shelves)[0] == expected


class TestHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Leviathan Wakes (The Expanse, #1)", ("Leviathan Wakes", "The Expanse", Decimal("1"))),
            ("Ember Road (The Long Road #2.5)", ("Ember Road", "The Long Road", Decimal("2.5"))),
            ("Dune", ("Dune", "", None)),
            ("Collected Stories (Volume One)", ("Collected Stories (Volume One)", "", None)),
            ("Omnibus (Series, #1-3)", ("Omnibus (Series, #1-3)", "", None)),  # ranges stay
        ],
    )
    def test_split_series(self, raw, expected):
        assert split_series(raw) == expected

    @pytest.mark.parametrize(
        ("isbn13", "isbn10", "expected"),
        [
            ('="9780593135204"', '=""', "9780593135204"),
            ("", '="0593135202"', "9780593135204"),
            ("", "080442957X", "9780804429573"),
            ('=""', '=""', ""),
            ("12345", "abc", ""),
        ],
    )
    def test_parse_isbn(self, isbn13, isbn10, expected):
        assert parse_isbn(isbn13, isbn10) == expected

    def test_map_row_without_id(self):
        assert map_row(1, {"Book Id": "", "Title": "X"}).error

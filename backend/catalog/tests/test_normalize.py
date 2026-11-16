import pytest

from catalog.services import normalize


class TestCleanDescription:
    def test_strips_tags_and_decodes_entities(self):
        raw = "<p>Grace &amp; the <b>Hail Mary</b> &#8212; it&#39;s far.</p>"
        assert normalize.clean_description(raw) == "Grace & the Hail Mary — it's far."

    def test_block_tags_become_line_breaks(self):
        raw = "<p>First.</p><p>Second.</p>Third<br>Fourth<br/>Fifth"
        assert normalize.clean_description(raw) == "First.\nSecond.\nThird\nFourth\nFifth"

    def test_collapses_blank_lines_and_spaces(self):
        raw = "One.<br><br><br>   Two   words.\r\n\r\n\r\nThree."
        assert normalize.clean_description(raw) == "One.\n\nTwo words.\n\nThree."

    def test_entity_decoded_after_tags_stays_text(self):
        # "&lt;3" is literal text in the source; it must survive as "<3", not be stripped.
        assert normalize.clean_description("I &lt;3 books") == "I <3 books"

    @pytest.mark.parametrize("raw", [None, "", "   ", "<p></p>"])
    def test_empty(self, raw):
        assert normalize.clean_description(raw) == ""


def test_clean_text():
    assert normalize.clean_text("  Dune&#58;  Messiah \n") == "Dune: Messiah"
    assert normalize.clean_text(None) == ""


class TestGoogleGenres:
    def test_splits_hierarchy_drops_general_and_dedupes(self):
        categories = ["Fiction / Science Fiction / General", "Fiction / Thrillers", "fiction"]
        assert normalize.genres_from_google_categories(categories) == (
            "Fiction",
            "Science Fiction",
            "Thrillers",
        )

    def test_none(self):
        assert normalize.genres_from_google_categories(None) == ()


class TestOpenLibraryGenres:
    def test_drops_catalog_noise(self):
        subjects = [
            "Science fiction",
            "Accessible book",
            "Protected DAISY",
            "In library",
            "Large type books",
            "New York Times bestseller",
            "nyt:hardcover-fiction=2021-05-23",
            "Hugo Award nominee",
            "2021",
            "Space flight",
        ]
        assert normalize.genres_from_open_library_subjects(subjects) == (
            "Science fiction",
            "Space flight",
        )

    def test_caps_count(self):
        subjects = [f"Subject {chr(65 + i)}" for i in range(20)]
        assert len(normalize.genres_from_open_library_subjects(subjects)) == 10


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("J.R.R. Tolkien", "jrr tolkien"),
        ("J. R. R. Tolkien", "jrr tolkien"),
        ("j r r  tolkien", "jrr tolkien"),
        ("JRR Tolkien", "jrr tolkien"),
        ("  Ursula K.  Le Guin ", "ursula k le guin"),  # lone middle initial stays
        ("N. K. Jemisin", "nk jemisin"),
        ("N.K. Jemisin", "nk jemisin"),
        ("ANDY WEIR", "andy weir"),
        ("A. A. Milne", "aa milne"),
        ("Mary Shelley", "mary shelley"),
    ],
)
def test_normalize_author_name(name, expected):
    assert normalize.normalize_author_name(name) == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("9780593135204", "9780593135204"),
        ("978-0-593-13520-4", "9780593135204"),
        ("0 593 13520 2", "0593135202"),
        ("080442957x", "080442957X"),
        ("project hail mary", None),
        ("12345", None),
        ("1234567890123", None),  # 13 digits but not a 978/979 prefix
    ],
)
def test_parse_isbn_query(query, expected):
    assert normalize.parse_isbn_query(query) == expected


def test_first_isbn_13_skips_isbn_10():
    assert normalize.first_isbn_13(["0593135202", "978-0-593-13520-4"]) == "9780593135204"
    assert normalize.first_isbn_13(["0593135202"]) == ""
    assert normalize.first_isbn_13(None) == ""


class TestPreferredIsbnLanguage:
    SPANISH, GERMAN = "9788418037016", "9783453322837"

    @pytest.mark.parametrize("english", ["9780593135204", "9781529157468", "9798217374274"])
    def test_english_prefixes_win_for_en(self, english):
        candidates = [self.SPANISH, self.GERMAN, english]
        assert normalize.first_isbn_13(candidates, "en") == english

    def test_first_english_one_wins_when_several(self):
        candidates = [self.SPANISH, "9781529157468", "9780593135204"]
        assert normalize.first_isbn_13(candidates, "en") == "9781529157468"

    def test_979_1_is_not_english(self):
        # 979-10 is France; only 979-8 is in the English set.
        # If 979-1 counted as English it would beat the first-listed Spanish ISBN.
        assert normalize.first_isbn_13([self.SPANISH, "9791028119676"], "en") == self.SPANISH

    def test_falls_back_to_first_valid_when_no_english(self):
        candidates = ["0593135202", self.SPANISH, self.GERMAN]
        assert normalize.first_isbn_13(candidates, "en") == self.SPANISH

    @pytest.mark.parametrize("language", [None, "", "fr", "de"])
    def test_other_languages_keep_first_valid(self, language):
        candidates = [self.SPANISH, "9780593135204"]
        assert normalize.first_isbn_13(candidates, language) == self.SPANISH


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "http://books.google.com/c?id=1&zoom=1&edge=curl",
            "https://books.google.com/c?id=1&zoom=1",
        ),
        (
            "https://covers.openlibrary.org/b/id/1-L.jpg",
            "https://covers.openlibrary.org/b/id/1-L.jpg",
        ),
        (None, ""),
    ],
)
def test_https_cover_url(url, expected):
    assert normalize.https_cover_url(url) == expected

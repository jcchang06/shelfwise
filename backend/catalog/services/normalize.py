"""Pure helpers that turn messy API data into clean catalog values. No I/O here."""

import html
import re
import unicodedata
from collections.abc import Iterable

from django.utils.html import strip_tags

_LINE_BREAK_TAGS = re.compile(r"<br\s*/?>|</p>|</li>|</h\d>", re.IGNORECASE)
_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_WHITESPACE = re.compile(r"\s+")


def clean_description(raw: str | None) -> str:
    """HTML description -> plain text (stored for display and for TF-IDF in Phase 3).

    Block tags become line breaks first, so "end.<br>Next" doesn't fuse into "end.Next".
    Then tags are stripped and entities decoded (&amp; -> &, &#39; -> ').
    """
    if not raw:
        return ""
    text = _LINE_BREAK_TAGS.sub("\n", raw)
    text = html.unescape(strip_tags(text))
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    text = "\n".join(lines)
    return _BLANK_LINES.sub("\n\n", text).strip()


def clean_text(raw: str | None) -> str:
    """Single-line text (titles, names): decode entities, collapse whitespace."""
    return _WHITESPACE.sub(" ", html.unescape(raw or "")).strip()


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return tuple(out)


def genres_from_google_categories(categories: Iterable[str] | None) -> tuple[str, ...]:
    """["Fiction / Science Fiction / General"] -> ("Science Fiction",)."""
    return normalize_genres(categories)


# Open Library subjects mix genres with catalog bookkeeping. These say nothing about the
# book's content and would only add noise to TF-IDF.
_OPEN_LIBRARY_NOISE = re.compile(
    r"accessible book|protected daisy|in library|lending library|large type|"
    r"overdrive|internet archive|open library|staff picks|nyt:|new york times|"
    r"reviewed|award|^fiction, general$|^general$|^\d|long now",
    re.IGNORECASE,
)
MAX_OPEN_LIBRARY_GENRES = 10


def genres_from_open_library_subjects(subjects: Iterable[str] | None) -> tuple[str, ...]:
    return normalize_genres(subjects)[:MAX_OPEN_LIBRARY_GENRES]


# Subjects and categories are often several genres joined into one string: Library of
# Congress style "Fiction, romance, general", Google's "Fiction / Romance / Contemporary".
_GENRE_SEPARATORS = re.compile(r"\s*[,/;]\s*")
_GENRE_FILLER = frozenset({"general", "etc", "etc."})


def _genre_case(piece: str) -> str:
    """All lowercase or all caps -> Title Case ("science fiction" -> "Science Fiction");
    mixed case is kept as written ("LGBTQ+ fiction" stays)."""
    return (
        " ".join(w[:1].upper() + w[1:].lower() for w in piece.split())
        if (piece.islower() or piece.isupper())
        else piece
    )


def normalize_genres(raw: Iterable[str] | None) -> tuple[str, ...]:
    """Stored genres (C-2, and R-1's TF-IDF): split joined values, drop filler ("General"),
    catalog noise and STATS_EXCLUDED_GENRES (Fiction, Nonfiction: they match nearly every
    book), fix all-lowercase or all-caps casing, and dedupe ignoring case (first wins).

    ["Fiction, romance, general", "Romance"] -> ("Romance",)
    """
    from django.conf import settings  # this module is otherwise settings-free

    excluded = {g.casefold() for g in settings.STATS_EXCLUDED_GENRES}
    pieces = (
        clean_text(piece)
        for value in raw or ()
        if isinstance(value, str) and not _OPEN_LIBRARY_NOISE.search(value)
        for piece in _GENRE_SEPARATORS.split(value)
    )
    kept = (
        _genre_case(piece)
        for piece in pieces
        if piece
        and piece.casefold() not in _GENRE_FILLER
        and piece.casefold() not in excluded
        and not _OPEN_LIBRARY_NOISE.search(piece)
    )
    return _dedupe(kept)


# A single-letter word followed by another single-letter word: the "j " in "j r r tolkien".
# Postgres spells the same pattern with \m / \M word anchors (see catalog.py).
INITIAL_RUN = re.compile(r"\b(\w) (?=\w\b)")


def normalize_author_name(name: str) -> str:
    """Matching key for authors.

    Lowercase, periods become spaces, whitespace collapses, then runs of initials are
    joined. So "J.R.R. Tolkien", "J. R. R. Tolkien" and "j r r  tolkien" all become
    "jrr tolkien", while a lone middle initial stays put ("ursula k le guin").
    Must stay in step with catalog.services.catalog._normalized_author_name.
    """
    spaced = _WHITESPACE.sub(" ", name.lower().replace(".", " ")).strip()
    return INITIAL_RUN.sub(r"\1", spaced)


_ISBN_CHARS = re.compile(r"[\s-]")
_ISBN_10 = re.compile(r"^\d{9}[\dX]$")
_ISBN_13 = re.compile(r"^97[89]\d{10}$")


def parse_isbn_query(query: str) -> str | None:
    """Return the bare ISBN if the search query *is* an ISBN-10 or ISBN-13, else None."""
    candidate = _ISBN_CHARS.sub("", query).upper()
    if _ISBN_13.match(candidate) or _ISBN_10.match(candidate):
        return candidate
    return None


# ISBN-13 prefixes for English-language registration groups: 978-0 and 978-1, plus 979-8
# (US, issued since 2020). Note 979-1x is France/Korea/Italy, so it's deliberately not "9791".
PREFERRED_ISBN_PREFIXES: dict[str, tuple[str, ...]] = {"en": ("9780", "9781", "9798")}


def first_isbn_13(candidates: Iterable[str] | None, language: str | None = None) -> str:
    """Pick one ISBN-13 from a list.

    Open Library's search `isbn` list mixes every edition in no useful order, so for a
    language with known prefixes (only "en" for now) the first ISBN in that language
    wins. Otherwise, or if none match, it's the first valid ISBN-13 as before. This keeps
    the same book from getting a foreign-edition ISBN from one source and the English
    one from the other, which would defeat ISBN matching on save.
    """
    bare = (_ISBN_CHARS.sub("", candidate) for candidate in candidates or ())
    valid = [isbn for isbn in bare if _ISBN_13.match(isbn)]
    preferred = PREFERRED_ISBN_PREFIXES.get(language or "", ())
    return next((isbn for isbn in valid if isbn.startswith(preferred)), valid[0] if valid else "")


def https_cover_url(url: str | None) -> str:
    """Google returns http:// thumbnails with a fake page-curl effect; fix both."""
    if not url:
        return ""
    url = url.replace("&edge=curl", "")
    return "https://" + url.removeprefix("http://") if url.startswith("http://") else url


_TRAILING_PARENS = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")
_NON_WORD = re.compile(r"[^\w\s]|_")


def normalize_title(title: str) -> str:
    """Matching key for titles: the main title (before ":"), without trailing bracketed
    notes like "(The Expanse, #1)" or "[Movie Tie-In]", accents stripped, "&" as "and",
    punctuation removed, lowercase, single spaces. "The Martian: A Novel" -> "the martian".
    """
    main = title.split(":", 1)[0]
    while _TRAILING_PARENS.search(main):
        main = _TRAILING_PARENS.sub("", main)
    decomposed = unicodedata.normalize("NFKD", main)
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    plain = plain.casefold().replace("&", " and ")
    return _WHITESPACE.sub(" ", _NON_WORD.sub(" ", plain)).strip()


def titles_compatible(a: str, b: str) -> bool:
    """Loose check that two titles name the same book, for vetting ISBN hits (some Open
    Library ISBNs are attached to the wrong work). Equal, one a prefix of the other, or at
    least half of the shorter title's words shared."""
    x, y = normalize_title(a), normalize_title(b)
    if not x or not y:
        return False
    if x == y or x.startswith(y) or y.startswith(x):
        return True
    wx, wy = set(x.split()), set(y.split())
    return len(wx & wy) >= max(1, min(len(wx), len(wy)) / 2)


def isbn10_to_13(isbn10: str) -> str:
    """ "0593135202" -> "9780593135204" (978 prefix, recomputed check digit)."""
    core = "978" + isbn10[:9]
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(core))
    return core + str((10 - total % 10) % 10)


def as_isbn_13(value: str) -> str:
    """Any ISBN-10 or ISBN-13 (hyphens/spaces allowed) as an ISBN-13, or "" if neither."""
    bare = parse_isbn_query(value or "")
    if bare is None:
        return ""
    return bare if len(bare) == 13 else isbn10_to_13(bare)


def title_author_key(title: str, first_author: str) -> tuple[str, str]:
    """The "same book" key: normalized title + first author (merge_duplicate_books' rule).
    Another edition or source of a book on the shelf has the same key."""
    return normalize_title(title), normalize_author_name(first_author)

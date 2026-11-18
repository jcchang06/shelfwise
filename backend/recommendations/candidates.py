"""Which books may be recommended, and series information (R-2, R-3).

A book that fails these checks stays in the TF-IDF matrix (it can still be one of the
reader's liked books) but is never picked and never shown as "more like this". Measured on
the 2026-10-31 seed (9,997 books) before choosing each rule; see implementation-notes.

- Omnibus / box set: several titles joined with " / ", or "box set", "omnibus",
  "collection", a title ending in "trilogy" or "quartet", "complete series", "(series)",
  or a numbered range in a series context ("#1-2", "Books 1-3", "(… 1-7)"). A plain
  "9-11" title is not a range, and "(Matched Trilogy, Book 3)" is one novel.
- Not a book to read: poster, colouring, sticker, activity or puzzle books, calendars,
  planners, guided journals, workbooks, official companions and guides, and fan fiction
  (genre). "A Good Girl's Guide to Murder" is a novel, so "guide" alone doesn't count.
  Known casualty: "Fangirl" (a novel tagged fan fiction).
- Not English: a title with a foreign-language cue (der, das, und, los, les, il, el, …,
  or ä ö ü ß ñ) and no English function word, or a description that is clearly another
  language. Known casualty: "El Deafo".
"""

import re
import unicodedata

_OMNIBUS = re.compile(
    r"\s/\s|\bbox(ed)?[\s-]?set\b|\bomnibus\b|\bcollection\b"
    # "Trilogy" ends the title only for the set itself, not "(Matched Trilogy, Book 3)".
    r"|\b(trilogy|quartet)\s*\)?\s*$"
    r"|\bcomplete (series|collection|novels)\b|\(series\)"
    r"|(#|\bbooks?\s+|\bvol(ume)?s?\.?\s*)\d+\s*[-–]\s*\d+"
    r"|\(\s*[^()]*?\b\d+\s*[-–]\s*\d+\s*\)",
    re.IGNORECASE,
)
_NOT_A_BOOK = re.compile(
    r"\bposter book\b|\bcolou?ring book\b|\bsticker book\b|\bactivity book\b|\bpuzzle book\b"
    r"|\bcalendar\b|\bplanner\b|\b(guided|gratitude|bullet|writing|prompt) journal\b"
    r"|\bworkbook\b|\bquiz book\b|\b(official|unofficial|ultimate|illustrated) (companion|guide)\b"
    r"|\bcompanion (guide|book)\b|\bguidebook\b"
    r"|\b(official|unofficial|ultimate)\b.*\bcompanion\b|\bcompanion\s*$",
    re.IGNORECASE,
)
_FAN_FICTION = {"fan fiction", "fanfiction"}

_FOREIGN_TITLE = re.compile(
    r"\b(der|das|und|des|dem|den|ein|eine|einer|vom|zum|im|los|las|el|del|y|une|les|aux"
    r"|dans|pour|il|della|och|het|een)\b|[äöüßñ]",
    re.IGNORECASE,
)
_ENGLISH_WORD = re.compile(r"\b(the|of|and|a|an|in|to|with|for|on|at|my|your)\b", re.IGNORECASE)
_LANG_WORDS = {
    "en": re.compile(r"\b(the|and|of|to|is|in|with|her|his|that)\b", re.IGNORECASE),
    "de": re.compile(r"\b(der|die|und|das|ist|nicht|mit|sich|ein|eine|auf)\b", re.IGNORECASE),
    "es": re.compile(r"\b(el|la|los|las|que|una|por|con|para|del)\b", re.IGNORECASE),
    "fr": re.compile(r"\b(le|la|les|et|une|des|est|dans|pour|qui)\b", re.IGNORECASE),
}

# "(The Dresden Files, Book 7)", "(Cirque Du Freak #1)", "(Time Quintet #3)"
_SERIES_MARKER = re.compile(
    r"\(([^()#]+?),?\s*(?:#|book\s+|vol\.?\s*|volume\s+|no\.?\s*)(\d+(?:\.\d+)?)\)\s*$",
    re.IGNORECASE,
)


def is_omnibus(title: str) -> bool:
    return bool(_OMNIBUS.search(title))


def is_not_a_book(title: str, genres: tuple[str, ...]) -> bool:
    return bool(_NOT_A_BOOK.search(title)) or any(g.casefold() in _FAN_FICTION for g in genres)


def description_language(description: str) -> str:
    """ "en", "de", "es", "fr", or "?" when there are too few function words to tell."""
    counts = {lang: len(pattern.findall(description)) for lang, pattern in _LANG_WORDS.items()}
    if sum(counts.values()) < 5:
        return "?"
    return max(counts, key=counts.get)


def is_foreign(title: str, description: str) -> bool:
    if _FOREIGN_TITLE.search(title) and not _ENGLISH_WORD.search(title):
        return True
    return description_language(description) not in ("en", "?")


def is_non_latin(title: str) -> bool:
    """Most of the title's letters are in another script (CJK, Cyrillic, Greek, …)."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    other = sum(1 for c in letters if not unicodedata.name(c, "").startswith("LATIN"))
    return other / len(letters) > 0.5


_MARKER_ONLY = re.compile(r"^\s*\([^()]*\)\s*$")


def is_marker_only(title: str) -> bool:
    """A title that is only a series marker, like "(Airhead #1)"."""
    return bool(_MARKER_ONLY.match(title))


_PICTURE_BOOK_GENRES = re.compile(r"picture books?|board books?|stories in rhyme", re.IGNORECASE)
_JUVENILE_GENRES = re.compile(r"juvenile|children", re.IGNORECASE)
MAX_PICTURE_BOOK_PAGES = 64
MIN_PLAUSIBLE_PAGES = 10  # counts below this are data errors ("Anna Dressed in Blood": 1)


MAX_TAGGED_PICTURE_BOOK_PAGES = 120  # "Charlie and the Chocolate Factory" (175) is tagged too


def is_picture_book(genres: tuple[str, ...], page_count: int | None) -> bool:
    """A picture-book genre (unless the book is long: one edition's tag can be wrong), or
    a juvenile work under 64 pages."""
    known = page_count is not None and page_count >= MIN_PLAUSIBLE_PAGES
    if any(_PICTURE_BOOK_GENRES.search(g) for g in genres):
        return not known or page_count < MAX_TAGGED_PICTURE_BOOK_PAGES
    short = known and page_count < MAX_PICTURE_BOOK_PAGES
    return short and any(_JUVENILE_GENRES.search(g) for g in genres)


EXCLUSION_RULES = ("marker_only", "omnibus", "not_a_book", "picture_book", "non_latin", "foreign")


def exclusion_reasons(
    title: str, description: str, genres: tuple[str, ...], page_count: int | None = None
) -> tuple[str, ...]:
    """Every rule the book fails, in EXCLUSION_RULES order (so one rule can be switched
    off to measure it without the book slipping past another)."""
    checks = {
        "marker_only": is_marker_only(title),
        "omnibus": is_omnibus(title),
        "not_a_book": is_not_a_book(title, genres),
        "picture_book": is_picture_book(genres, page_count),
        "non_latin": is_non_latin(title),
        "foreign": is_foreign(title, description),
    }
    return tuple(rule for rule in EXCLUSION_RULES if checks[rule])


def exclusion_reason(
    title: str, description: str, genres: tuple[str, ...], page_count: int | None = None
) -> str | None:
    """Why a book can't be recommended (the first rule it fails), or None."""
    reasons = exclusion_reasons(title, description, genres, page_count)
    return reasons[0] if reasons else None


def series_key(name: str) -> str:
    """ "The Dresden Files" and "Dresden Files series" -> "dresden files"."""
    words = re.sub(r"[^\w\s]", " ", name.casefold()).split()
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in ("series", "saga", "books", "novels"):
        words = words[:-1]
    return " ".join(words)


_ORDINALS = {
    word: n
    for n, word in enumerate(
        "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth".split(),
        start=1,
    )
}
# "the third book in the Crescent City series", "Book 5 of the Mortal Instruments saga",
# "sixth novel in Diana Gabaldon's bestselling Outlander saga". Needs both a number and a
# named series; an ordinal alone ("her second novel") is too common to mean anything.
_DESCRIPTION_SERIES = re.compile(
    r"\b(?:(?P<ordinal>" + "|".join(_ORDINALS) + r"|\d+(?:st|nd|rd|th)?)\s+"
    r"(?:book|novel|installment|instalment|volume|title|adventure)"
    r"|(?:book|#|no\.?)\s*(?P<number>\d+))\s+(?:in|of)\s+(?:the\s+)?"
    r"(?P<name>[^.;:!?()]{2,80}?)\s+(?:series|saga|sequence|cycle|chronicles)\b",
    re.IGNORECASE,
)
_CONNECTORS = {"of", "the", "and", "de", "du", "la", "le"}
# A trailing "Book 7" / "#10" / "Vol. 2" in the title, with no series name.
_TITLE_NUMBER = re.compile(r"(?:\bbook|#|\bvol(?:ume)?\.?|\bpart)\s*(\d+)\s*\)?\s*$", re.IGNORECASE)


def _series_name_from(text: str) -> str:
    """The series name from a description phrase: the last run of capitalized words, so
    "Diana Gabaldon's bestselling Outlander" -> "Outlander" and "NYT best-selling
    Expanse" -> "Expanse"."""
    runs: list[list[str]] = []
    current: list[str] = []
    for word in re.findall(r"[\w'’-]+", text):
        capital = word[:1].isupper() or word[:1].isdigit()
        if capital:  # possessives too: "Ranger's Apprentice" (an author's name ends its
            current.append(word)  # run at the next lowercase word: "Gabaldon's bestselling")
        elif current and word.lower() in _CONNECTORS:
            current.append(word)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)
    if not runs:
        return ""
    last = runs[-1]
    while last and last[-1].lower() in _CONNECTORS:
        last = last[:-1]
    return " ".join(last)


def series_from_description(description: str) -> tuple[str, float | None]:
    match = _DESCRIPTION_SERIES.search(description)
    if not match:
        return "", None
    raw = (match.group("ordinal") or "").lower()
    number = _ORDINALS.get(raw) or int(re.sub(r"\D", "", raw or match.group("number")))
    name = _series_name_from(match.group("name"))
    return (series_key(name), float(number)) if name else ("", None)


SERIES_SOURCES = ("catalog", "marker", "description", "title_number")


def series_with_source(
    title: str, series_name: str, series_number, description: str = ""
) -> tuple[str, float | None, str]:
    """(series key, number, source) from, in order: the catalog's series fields
    ("catalog"), the title's marker ("marker"), a description phrase naming the series and
    the number ("description"), or a trailing "Book N" / "#N" in the title ("title_number",
    series name unknown: key "?"). ("", None, "") otherwise."""
    if series_name:
        number = float(series_number) if series_number is not None else None
        return series_key(series_name), number, "catalog"
    match = _SERIES_MARKER.search(title)
    if match:
        return series_key(match.group(1)), float(match.group(2)), "marker"
    key, number = series_from_description(description)
    if key:
        return key, number, "description"
    numbered = _TITLE_NUMBER.search(title)
    if numbered:
        return UNKNOWN_SERIES, float(numbered.group(1)), "title_number"
    return "", None, ""


def series_of(
    title: str, series_name: str, series_number, description: str = ""
) -> tuple[str, float | None]:
    """series_with_source without the source."""
    key, number, _ = series_with_source(title, series_name, series_number, description)
    return key, number


# A book known to be numbered in some series whose name we don't know.
UNKNOWN_SERIES = "?"

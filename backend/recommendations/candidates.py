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


def exclusion_reason(title: str, description: str, genres: tuple[str, ...]) -> str | None:
    """Why a book can't be recommended ("omnibus", "not_a_book", "foreign"), or None."""
    if is_omnibus(title):
        return "omnibus"
    if is_not_a_book(title, genres):
        return "not_a_book"
    if is_foreign(title, description):
        return "foreign"
    return None


def series_key(name: str) -> str:
    """ "The Dresden Files" and "Dresden Files series" -> "dresden files"."""
    words = re.sub(r"[^\w\s]", " ", name.casefold()).split()
    if words and words[0] == "the":
        words = words[1:]
    while words and words[-1] in ("series", "saga", "books", "novels"):
        words = words[:-1]
    return " ".join(words)


def series_of(title: str, series_name: str, series_number) -> tuple[str, float | None]:
    """(series key, number) from the catalog's series fields, else the title's marker;
    ("", None) when the book isn't known to be in a series."""
    if series_name:
        number = float(series_number) if series_number is not None else None
        return series_key(series_name), number
    match = _SERIES_MARKER.search(title)
    if match:
        return series_key(match.group(1)), float(match.group(2))
    return "", None

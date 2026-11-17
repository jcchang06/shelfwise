from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    GOOGLE_BOOKS = "google_books"
    OPEN_LIBRARY = "open_library"


@dataclass(frozen=True)
class AuthorRef:
    name: str
    open_library_key: str | None = None  # e.g. "OL23919A"; Google Books has no author IDs


@dataclass(frozen=True)
class BookResult:
    """A book as returned by any source, already cleaned up (see normalize.py)."""

    source: Source
    source_id: str  # Google volume ID or Open Library work key ("OL82563W")
    title: str
    authors: tuple[AuthorRef, ...] = ()
    description: str = ""
    genres: tuple[str, ...] = ()
    page_count: int | None = None
    published_date: str = ""  # raw partial date ("2014", "2014-03"); parsed on save
    isbn_13: str = ""
    cover_url: str = ""


@dataclass(frozen=True)
class AuthorWork:
    """One work in an author's Open Library bibliography (C-5; the release check N-2)."""

    work_key: str  # "OL82563W"
    title: str
    first_publish_year: int | None = None
    cover_url: str = ""
    edition_count: int = 0


@dataclass(frozen=True)
class AuthorCandidate:
    """An Open Library author search hit."""

    key: str  # "OL31353A"
    name: str
    alternate_names: tuple[str, ...] = ()
    work_count: int = 0


@dataclass(frozen=True)
class SearchResults:
    source: Source
    results: list[BookResult]


class BookSourceError(Exception):
    """A book API could not be reached or returned an unusable response."""


class QuotaExceededError(BookSourceError):
    """Google Books' daily quota is used up; callers should go to the fallback source."""


class RateLimitedError(BookSourceError):
    """Google Books' short-term (per-minute) rate limit was hit. Transient: try again in a
    moment or use the fallback source; unlike QuotaExceededError it doesn't last all day."""


class BookNotFoundError(Exception):
    """The source has no book with the requested ID."""


class BookSearchUnavailableError(Exception):
    """Every source failed, so search can't answer right now."""

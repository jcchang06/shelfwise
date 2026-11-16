"""Book search across sources (C-1): Google Books first, Open Library as the fallback."""

import logging

from . import google_books, open_library
from .types import BookSearchUnavailableError, BookSourceError, SearchResults, Source

logger = logging.getLogger(__name__)


def search_books(query: str, page: int = 1) -> SearchResults:
    """Search Google Books; use Open Library if Google fails, is over quota, or finds nothing.

    Raises BookSearchUnavailableError only when no source could answer at all.
    """
    google_results = None
    try:
        google_results = google_books.search(query, page)
        if google_results:
            return SearchResults(Source.GOOGLE_BOOKS, google_results)
    except BookSourceError as exc:  # includes QuotaExceededError
        logger.info("Google Books search failed (%s); falling back to Open Library", exc)

    try:
        return SearchResults(Source.OPEN_LIBRARY, open_library.search(query, page))
    except BookSourceError as exc:
        if google_results is not None:
            # Google answered (with nothing); an empty answer beats an error.
            return SearchResults(Source.GOOGLE_BOOKS, google_results)
        raise BookSearchUnavailableError("No book source is reachable") from exc

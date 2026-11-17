"""Shared HTTP plumbing for the book API clients."""

import logging
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .types import BookSourceError

logger = logging.getLogger(__name__)

# (connect, read) seconds. Search runs inside a user request, so keep the worst case short;
# a slow source should fall back quickly rather than hang the page.
REQUEST_TIMEOUT = (3, 5)
# One retry for user-facing calls. Background jobs (later phases) pass retries=3 to match
# the PRD's reliability requirement.
REQUEST_RETRIES = 1


def build_session(retries: int = REQUEST_RETRIES) -> requests.Session:
    retry = Retry(
        total=retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        # Return the final response instead of raising, so callers can tell a quota 429
        # from an outage; and don't sleep for whatever Retry-After the server asks.
        raise_on_status=False,
        respect_retry_after_header=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    # The User-Agent is set per request in get_response, not here: this session is cached
    # for the process, and a header baked in at creation would ignore later setting changes.
    session.headers.update({"Accept": "application/json"})
    return session


def get_response(
    session: requests.Session, url: str, params: dict[str, Any] | None = None
) -> requests.Response:
    """GET with the standard timeout. Network failures become BookSourceError."""
    try:
        return session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": settings.OPEN_LIBRARY_USER_AGENT},
        )
    except requests.RequestException as exc:
        # Log the URL without the query string: Google's includes the API key.
        logger.warning("Book API request to %s failed: %s", url, type(exc).__name__)
        raise BookSourceError(f"Request to {url} failed") from exc


def parse_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise BookSourceError(f"Non-JSON response from {response.url.split('?')[0]}") from exc

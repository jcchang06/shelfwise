import json
import re
from pathlib import Path
from typing import Any

import pytest
import responses

from catalog.services import google_books, open_library

FIXTURES = Path(__file__).parent / "fixtures"

GOOGLE_VOLUMES = f"{google_books.API_ROOT}/volumes"
OL_SEARCH = f"{open_library.API_ROOT}/search.json"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def google_volume_url(volume_id: str) -> str:
    return f"{GOOGLE_VOLUMES}/{volume_id}"


def ol_work_url(work_key: str) -> str:
    return f"{open_library.API_ROOT}/works/{work_key}.json"


# Matches the search URL with any query string (responses ignores query by default for
# plain strings, but a regex makes that explicit for readers).
GOOGLE_SEARCH_RE = re.compile(re.escape(GOOGLE_VOLUMES) + r"(\?.*)?$")
OL_SEARCH_RE = re.compile(re.escape(OL_SEARCH) + r"(\?.*)?$")


@pytest.fixture
def mocked():
    """Every test that touches a service gets this: unregistered URLs raise, so no test
    can reach the network by accident."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture(autouse=True)
def _book_api_settings(settings):
    settings.GOOGLE_BOOKS_API_KEY = "test-key"
    settings.BOOK_SEARCH_LANGUAGE = "en"
    settings.OPEN_LIBRARY_USER_AGENT = "Shelfwise-tests/0.1"

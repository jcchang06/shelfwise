import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def _locmem_cache(settings):
    """Tests use an in-memory cache instead of the production database cache.

    Overriding CACHES makes Django rebuild its cache handlers, so `cache` below is
    the locmem one. Clearing it keeps throttle counters and API caches from
    leaking between tests.
    """
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "shelfwise-tests",
        }
    }
    settings.OPEN_LIBRARY_REQUESTS_PER_SECOND = 0  # no sleeping in tests
    settings.IMPORT_GOOGLE_REQUESTS_PER_SECOND = 0
    cache.clear()
    yield
    cache.clear()

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache; without this, one test's requests count against the next.
    cache.clear()
    yield
    cache.clear()

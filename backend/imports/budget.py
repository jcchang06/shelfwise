"""The import's share of the Google Books daily quota (IMPORT_GOOGLE_DAILY_BUDGET).

Google's free quota is 1,000 requests a day, reset at midnight Pacific, and shared with
search. Imports may spend at most the budget per Pacific day; the counter lives in the
shared (database) cache so every process and the nightly job see the same number.
"""

import datetime as dt

from django.conf import settings
from django.core.cache import cache

from catalog.services.google_books import PACIFIC, quota_exhausted


class BudgetExhaustedError(Exception):
    """No Google calls left for imports today (or Google's own quota is used up)."""


def _key(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(tz=dt.UTC)
    return f"imports:google_calls:{now.astimezone(PACIFIC).date().isoformat()}"


def google_calls_used(now: dt.datetime | None = None) -> int:
    return int(cache.get(_key(now)) or 0)


def spend_google_call(now: dt.datetime | None = None) -> None:
    """Count one Google call against today's budget, or raise if none are left.

    Counted before the call (conservatively: a call served from the search cache still
    counts), so a crash mid-call can't let an import overspend.
    """
    if quota_exhausted():
        raise BudgetExhaustedError("Google Books' daily quota is used up until midnight Pacific.")
    key = _key(now)
    cache.add(key, 0, timeout=2 * 24 * 60 * 60)  # expires on its own after the day ends
    used = cache.incr(key)
    if used > settings.IMPORT_GOOGLE_DAILY_BUDGET:
        raise BudgetExhaustedError(
            f"The import's Google budget ({settings.IMPORT_GOOGLE_DAILY_BUDGET} a day) is used "
            "up until midnight Pacific."
        )

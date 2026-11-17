import datetime as dt

import pytest
from django.core.cache import cache

from catalog.services import google_books
from imports.budget import BudgetExhaustedError, google_calls_used, spend_google_call

UTC = dt.UTC


def test_counts_calls_per_pacific_day(settings):
    settings.IMPORT_GOOGLE_DAILY_BUDGET = 5
    morning = dt.datetime(2026, 11, 16, 16, 0, tzinfo=UTC)  # 08:00 PST
    spend_google_call(morning)
    spend_google_call(morning)
    assert google_calls_used(morning) == 2


def test_raises_once_the_budget_is_spent(settings):
    settings.IMPORT_GOOGLE_DAILY_BUDGET = 2
    now = dt.datetime(2026, 11, 16, 16, 0, tzinfo=UTC)
    spend_google_call(now)
    spend_google_call(now)
    with pytest.raises(BudgetExhaustedError, match="2 a day"):
        spend_google_call(now)


def test_resets_at_midnight_pacific_not_utc(settings):
    settings.IMPORT_GOOGLE_DAILY_BUDGET = 1
    late_pst = dt.datetime(2026, 11, 17, 7, 59, tzinfo=UTC)  # 23:59 PST, Nov 16
    spend_google_call(late_pst)
    with pytest.raises(BudgetExhaustedError):
        spend_google_call(dt.datetime(2026, 11, 17, 7, 59, 30, tzinfo=UTC))
    # 00:00 PST Nov 17: a new day (UTC had already been "Nov 17" for hours).
    spend_google_call(dt.datetime(2026, 11, 17, 8, 0, tzinfo=UTC))


def test_respects_googles_own_quota_flag():
    cache.set(google_books.QUOTA_FLAG_KEY, True)
    with pytest.raises(BudgetExhaustedError, match="quota"):
        spend_google_call()
    assert google_calls_used() == 0  # nothing counted

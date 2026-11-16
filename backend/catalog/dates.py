"""Partial publish dates from book APIs ("2014", "2014-03", "2014-03-05")."""

import datetime as dt
import re

from django.db import models


class DatePrecision(models.TextChoices):
    YEAR = "year", "Year"
    MONTH = "month", "Month"
    DAY = "day", "Day"


_PARTIAL_DATE = re.compile(r"^(?P<year>\d{4})(?:-(?P<month>\d{1,2})(?:-(?P<day>\d{1,2}))?)?")


def parse_partial_date(raw: str | None) -> tuple[dt.date | None, str]:
    """Parse an API date string into (earliest matching date, precision).

    Returns (None, "") for anything unparseable rather than raising: bad metadata
    from an external API shouldn't block saving a book.
    """
    if not raw:
        return None, ""
    match = _PARTIAL_DATE.match(raw.strip())
    if not match:
        return None, ""
    year = int(match["year"])
    month = int(match["month"]) if match["month"] else None
    day = int(match["day"]) if match["day"] else None
    try:
        if day is not None:
            return dt.date(year, month or 1, day), DatePrecision.DAY
        if month is not None:
            return dt.date(year, month, 1), DatePrecision.MONTH
        return dt.date(year, 1, 1), DatePrecision.YEAR
    except ValueError:  # e.g. "2014-13" or "2014-02-30"
        return None, ""

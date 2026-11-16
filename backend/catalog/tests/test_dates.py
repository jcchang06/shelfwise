import datetime as dt

import pytest

from catalog.dates import DatePrecision, parse_partial_date


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2014", (dt.date(2014, 1, 1), DatePrecision.YEAR)),
        ("2014-03", (dt.date(2014, 3, 1), DatePrecision.MONTH)),
        ("2014-03-05", (dt.date(2014, 3, 5), DatePrecision.DAY)),
        (" 2014-3-5 ", (dt.date(2014, 3, 5), DatePrecision.DAY)),
        ("2014-03-05T00:00:00Z", (dt.date(2014, 3, 5), DatePrecision.DAY)),
    ],
)
def test_parses_partial_dates(raw, expected):
    assert parse_partial_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "March 2014", "2014-13", "2014-02-30", "14"])
def test_unparseable_dates_return_empty(raw):
    assert parse_partial_date(raw) == (None, "")

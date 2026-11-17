"""Dashboard stats (T-5). One function per section, combined by stats_for().

Counting rules:
- pages_per_month: every log in the year by log_date. `dnf_pages` is the part logged on
  books that are currently DNF; those pages were read, so they're in `pages` too.
- books_per_year: finished = entries with status finished, by finished_at's year;
  dnf = entries with status dnf, by dnf_at's year. Entries with no such date go in a
  final {"year": None} row ("Date unknown" in the UI), so totals reconcile after a
  Goodreads import. A re-read in progress (status reading) isn't counted as finished.
- genre_mix: finished and DNF books dated in the year; each genre once per book, merged
  case-insensitively, STATS_EXCLUDED_GENRES left out, top 8 plus "Other".
- rating_distribution: rated books whose finished_at is in the year (so a re-read keeps
  its stars here). DNF books never have a rating.

v1 keeps no per-read history, so a book finished twice counts once, in its latest year.
About five grouped queries per call.
"""

from collections import Counter, defaultdict
from typing import Any

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from .models import ReadingLog, UserBook

Status = UserBook.Status
TOP_GENRES = 8
OTHER = "Other"


def pages_per_month(user, year: int) -> list[dict[str, Any]]:
    currently_dnf = UserBook.objects.filter(
        user=OuterRef("user"), book=OuterRef("book"), status=Status.DNF
    )
    rows = (
        ReadingLog.objects.filter(user=user, log_date__year=year)
        .annotate(month=ExtractMonth("log_date"), is_dnf=Exists(currently_dnf))
        .values("month")
        .annotate(pages=Sum("pages_read"), dnf_pages=Sum("pages_read", filter=Q(is_dnf=True)))
    )
    by_month = {row["month"]: row for row in rows}
    return [
        {
            "month": f"{year}-{month:02d}",
            "pages": (by_month.get(month) or {}).get("pages") or 0,
            "dnf_pages": (by_month.get(month) or {}).get("dnf_pages") or 0,
        }
        for month in range(1, 13)
    ]


def books_per_year(user) -> list[dict[str, Any]]:
    counts: dict[int | None, dict[str, int]] = defaultdict(lambda: {"finished": 0, "dnf": 0})
    for status, date_field, key in (
        (Status.FINISHED, "finished_at", "finished"),
        (Status.DNF, "dnf_at", "dnf"),
    ):
        rows = (
            UserBook.objects.filter(user=user, status=status)
            .annotate(year=ExtractYear(date_field))  # NULL date -> year None
            .values("year")
            .annotate(n=Count("id"))
        )
        for row in rows:
            counts[row["year"]][key] += row["n"]

    dated = sorted(year for year in counts if year is not None)
    ordered = [*dated, None] if None in counts else dated
    return [{"year": year, **counts[year]} for year in ordered]


def genre_mix(user, year: int) -> list[dict[str, Any]]:
    excluded = {label.casefold() for label in settings.STATS_EXCLUDED_GENRES}
    entries = UserBook.objects.filter(
        Q(status=Status.FINISHED, finished_at__year=year) | Q(status=Status.DNF, dnf_at__year=year),
        user=user,
    ).values_list("status", "book__genres")

    counts: dict[str, Counter] = defaultdict(Counter)  # casefolded genre -> {finished, dnf}
    spellings: dict[str, Counter] = defaultdict(Counter)  # casefolded -> original spellings
    for status, genres in entries:
        seen: set[str] = set()
        for genre in genres or ():
            label = genre.strip()
            key = label.casefold()
            if not label or key in excluded or key in seen:
                continue
            seen.add(key)
            spellings[key][label] += 1
            counts[key]["finished" if status == Status.FINISHED else "dnf"] += 1

    def display(key: str) -> str:
        # Most common spelling wins; ties go to the alphabetically first for stable output.
        return min(spellings[key].items(), key=lambda item: (-item[1], item[0]))[0]

    ranked = sorted(
        counts,
        key=lambda k: (-(counts[k]["finished"] + counts[k]["dnf"]), display(k).casefold()),
    )
    rows = [
        {"genre": display(k), "finished": counts[k]["finished"], "dnf": counts[k]["dnf"]}
        for k in ranked[:TOP_GENRES]
    ]
    rest = ranked[TOP_GENRES:]
    if rest:
        rows.append(
            {
                "genre": OTHER,
                "finished": sum(counts[k]["finished"] for k in rest),
                "dnf": sum(counts[k]["dnf"] for k in rest),
            }
        )
    return rows


def rating_distribution(user, year: int) -> list[dict[str, int]]:
    rows = (
        UserBook.objects.filter(user=user, rating__isnull=False, finished_at__year=year)
        .values("rating")
        .annotate(n=Count("id"))
    )
    by_stars = {row["rating"]: row["n"] for row in rows}
    return [{"stars": stars, "books": by_stars.get(stars, 0)} for stars in range(1, 6)]


def stats_for(user, year: int) -> dict[str, Any]:
    pages = pages_per_month(user, year)
    per_year = books_per_year(user)
    ratings = rating_distribution(user, year)

    this_year = next((row for row in per_year if row["year"] == year), {"finished": 0, "dnf": 0})
    rated = sum(row["books"] for row in ratings)
    average = (
        round(sum(row["stars"] * row["books"] for row in ratings) / rated, 1) if rated else None
    )
    return {
        "year": year,
        "totals": {
            "pages": sum(row["pages"] for row in pages),
            "finished": this_year["finished"],
            "dnf": this_year["dnf"],
            "average_rating": average,
        },
        "pages_per_month": pages,
        "books_per_year": per_year,
        "genre_mix": genre_mix(user, year),
        "rating_distribution": ratings,
    }

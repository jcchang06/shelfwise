"""Sort key for the shelf's "Author (A-Z)" order (T-2): the first author's last name.

Worked out in Postgres, inside the shelf query, so the list stays at a fixed number of
queries. The rule, on the lowercased name with whitespace collapsed:

1. Strip a trailing suffix: Jr., Sr., II, III, IV (with or without a comma or period).
2. If the word before the last one is a surname particle (le, la, de, du, da, di, del,
   van, von, der), the key is "particle last": "Ursula K. Le Guin" -> "le guin",
   "Daphne du Maurier" -> "du maurier".
3. Otherwise the key is the last word: "Martin Luther King Jr." -> "king".

A book with no author has no key, and sorts last.
"""

from django.db.models import CharField, Func, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce, Lower, Trim

from catalog.models import BookAuthor

PARTICLES = ("le", "la", "de", "du", "da", "di", "del", "van", "von", "der")
SUFFIX_PATTERN = r"[\s,]+(jr|sr|ii|iii|iv)\.?$"
PARTICLE_PATTERN = rf"(?:^|\s)((?:{'|'.join(PARTICLES)})\s\S+)$"
LAST_WORD_PATTERN = r"(\S+)$"


class _RegexpReplace(Func):
    function = "REGEXP_REPLACE"
    output_field = CharField()


class _FirstMatch(Func):
    """(REGEXP_MATCH(text, pattern))[1]: the first group, or NULL when it doesn't match."""

    template = "(REGEXP_MATCH(%(expressions)s))[1]"
    output_field = CharField()


def author_sort_key(name_expression):
    spaced = _RegexpReplace(Lower(Trim(name_expression)), Value(r"\s+"), Value(" "), Value("g"))
    no_suffix = Trim(_RegexpReplace(spaced, Value(SUFFIX_PATTERN), Value("")))
    return Coalesce(
        _FirstMatch(no_suffix, Value(PARTICLE_PATTERN)),
        _FirstMatch(no_suffix, Value(LAST_WORD_PATTERN)),
        output_field=CharField(),
    )


def first_author_name():
    """The shelf entry's book's first credited author, as a correlated subquery."""
    first = BookAuthor.objects.filter(book=OuterRef("book")).order_by("position", "id")
    return Subquery(first.values("author__name")[:1], output_field=CharField())


def with_author_sort_key(queryset):
    return queryset.annotate(author_sort=author_sort_key(first_author_name()))

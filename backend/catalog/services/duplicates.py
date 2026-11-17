"""Find and merge the same book saved more than once in the catalog (e.g. once from Google
Books and once from Open Library with different ISBNs).

A group is books with the same normalized title and first author. The keeper is the
oldest; the others are merged into it. A group is NOT merged when one user has shelf
entries or logs on more than one of its books (merging would collide); those are reported
for a person to sort out.

Safety (by design): the command only merges with --apply <token>, where the token is a
hash of the exact plan printed by --dry-run. If the catalog changed since, the token no
longer matches and nothing happens.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from catalog.models import Book, BookAuthor
from catalog.services.normalize import normalize_author_name, normalize_title

# Book fields copied from a duplicate when the keeper's is empty.
FILLABLE = ("description", "genres", "page_count", "cover_url", "series_name", "series_number")


@dataclass
class DuplicateGroup:
    title_key: str
    author_key: str
    keeper: Book
    duplicates: list[Book]
    conflicts: list[str] = field(default_factory=list)  # why it can't be merged automatically

    @property
    def mergeable(self) -> bool:
        return not self.conflicts


def _first_author_key(book: Book) -> str:
    links = sorted(book.book_authors.all(), key=lambda ba: ba.position)
    return normalize_author_name(links[0].author.name) if links else ""


def _conflicts(books: list[Book]) -> list[str]:
    from tracking.models import ReadingLog, UserBook  # tracking depends on catalog

    ids = [b.id for b in books]
    per_user: dict[int, set[int]] = defaultdict(set)
    for user_id, book_id in UserBook.objects.filter(book_id__in=ids).values_list(
        "user_id", "book_id"
    ):
        per_user[user_id].add(book_id)
    for user_id, book_id in ReadingLog.objects.filter(book_id__in=ids).values_list(
        "user_id", "book_id"
    ):
        per_user[user_id].add(book_id)
    return [
        f"user {user_id} has shelf entries or logs on books {sorted(book_ids)}"
        for user_id, book_ids in sorted(per_user.items())
        if len(book_ids) > 1
    ]


def find_duplicate_groups() -> list[DuplicateGroup]:
    books = Book.objects.prefetch_related("book_authors__author").order_by("created_at", "id")
    groups: dict[tuple[str, str], list[Book]] = defaultdict(list)
    for book in books:
        author_key = _first_author_key(book)
        title_key = normalize_title(book.title)
        if author_key and title_key:  # without an author, a title alone is too weak
            groups[(title_key, author_key)].append(book)
    result = []
    for (title_key, author_key), members in groups.items():
        if len(members) > 1:
            keeper, *duplicates = members  # already oldest first
            result.append(
                DuplicateGroup(title_key, author_key, keeper, duplicates, _conflicts(members))
            )
    return sorted(result, key=lambda g: g.keeper.id)


def plan_token(groups: list[DuplicateGroup]) -> str:
    """Short hash of exactly what --apply would do (keepers, duplicates, mergeability)."""
    plan = ";".join(
        f"{g.keeper.id}<-{','.join(str(d.id) for d in g.duplicates)}:{int(g.mergeable)}"
        for g in groups
    )
    return hashlib.sha256(plan.encode()).hexdigest()[:12]


@transaction.atomic
def merge_group(group: DuplicateGroup) -> None:
    """Merge every duplicate into the keeper. Only call for mergeable groups."""
    from imports.models import ImportRow
    from tracking.models import ReadingLog, UserBook

    if not group.mergeable:
        raise ValueError("This group has conflicts and must be resolved by hand.")
    keeper = Book.objects.select_for_update().get(pk=group.keeper.pk)
    changed: set[str] = set()
    for dup in group.duplicates:
        dup = Book.objects.select_for_update().get(pk=dup.pk)
        # Move references first (Book FKs are PROTECT).
        UserBook.objects.filter(book=dup).update(book=keeper)
        ReadingLog.objects.filter(book=dup).update(book=keeper)
        ImportRow.objects.filter(book=dup).update(book=keeper)

        for name in FILLABLE:
            if not getattr(keeper, name) and getattr(dup, name):
                setattr(keeper, name, getattr(dup, name))
                changed.add(name)
        if keeper.published_date is None and dup.published_date is not None:
            keeper.published_date = dup.published_date
            keeper.published_date_precision = dup.published_date_precision
            changed |= {"published_date", "published_date_precision"}
        if not keeper.isbn_13 and dup.isbn_13:
            keeper.isbn_13 = dup.isbn_13
            changed.add("isbn_13")

        # Source IDs are unique: take them off the duplicate before giving them to the keeper.
        moved = {}
        for id_field in ("google_books_id", "open_library_key"):
            if not getattr(keeper, id_field) and getattr(dup, id_field):
                moved[id_field] = getattr(dup, id_field)
        if moved:
            Book.objects.filter(pk=dup.pk).update(**dict.fromkeys(moved, None))
            for id_field, value in moved.items():
                setattr(keeper, id_field, value)
                changed.add(id_field)

        if not keeper.book_authors.exists():
            BookAuthor.objects.filter(book=dup).update(book=keeper)
        Book.objects.filter(pk=dup.pk).delete()  # its remaining BookAuthor rows cascade

    if changed:
        keeper.save(update_fields=[*sorted(changed), "updated_at"])

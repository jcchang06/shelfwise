import datetime as dt

import pytest
from django.db import IntegrityError

from catalog.dates import DatePrecision
from catalog.models import Book, BookAuthor

from .factories import AuthorFactory, BookFactory

pytestmark = pytest.mark.django_db


def test_authors_keep_credit_order():
    first, second = AuthorFactory(name="Zadie"), AuthorFactory(name="Adam")
    book = BookFactory(authors=[first, second])
    ordered = [ba.author for ba in BookAuthor.objects.filter(book=book)]
    assert ordered == [first, second]
    assert set(book.authors.all()) == {first, second}


def test_author_linked_once_per_book():
    author = AuthorFactory()
    book = BookFactory(authors=[author])
    with pytest.raises(IntegrityError):
        BookAuthor.objects.create(book=book, author=author, position=1)


def test_external_ids_unique_but_nullable():
    # Several books with no external IDs are fine (NULLs don't collide)...
    Book.objects.create(title="Hand-entered A")
    Book.objects.create(title="Hand-entered B")
    # ...but a repeated Google Books ID is rejected.
    BookFactory(google_books_id="abc123")
    with pytest.raises(IntegrityError):
        BookFactory(google_books_id="abc123")


def test_isbn_not_unique():
    # Google Books can return two volume IDs for one ISBN; both must be storable.
    BookFactory(isbn_13="9780000000001")
    BookFactory(isbn_13="9780000000001")
    assert Book.objects.filter(isbn_13="9780000000001").count() == 2


def test_published_date_requires_precision():
    with pytest.raises(IntegrityError):
        BookFactory(published_date=dt.date(2014, 1, 1), published_date_precision="")


def test_precision_requires_published_date():
    with pytest.raises(IntegrityError):
        BookFactory(published_date=None, published_date_precision=DatePrecision.YEAR)


@pytest.mark.parametrize(
    ("precision", "expected"),
    [
        (DatePrecision.YEAR, "2014"),
        (DatePrecision.MONTH, "2014-03"),
        (DatePrecision.DAY, "2014-03-05"),
    ],
)
def test_published_date_display_respects_precision(precision, expected):
    book = BookFactory.build(published_date=dt.date(2014, 3, 5), published_date_precision=precision)
    assert book.published_date_display == expected


def test_published_date_display_empty_without_date():
    book = BookFactory.build(published_date=None, published_date_precision="")
    assert book.published_date_display == ""


def test_series_number_allows_half_numbers():
    book = BookFactory(series_name="The Expanse", series_number="2.5")
    book.refresh_from_db()
    assert str(book.series_number) == "2.5"


def test_str():
    assert str(BookFactory.build(title="Piranesi")) == "Piranesi"
    assert str(AuthorFactory.build(name="Susanna Clarke")) == "Susanna Clarke"

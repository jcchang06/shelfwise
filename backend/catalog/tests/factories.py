import datetime as dt

import factory

from catalog.dates import DatePrecision
from catalog.models import Author, Book, BookAuthor


class AuthorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Author

    name = factory.Faker("name")


class BookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Book
        skip_postgeneration_save = True

    google_books_id = factory.Sequence(lambda n: f"gb{n:06d}")
    isbn_13 = factory.Sequence(lambda n: f"978{n:010d}")
    title = factory.Faker("sentence", nb_words=3)
    description = factory.Faker("paragraph")
    genres = factory.LazyFunction(lambda: ["Fiction"])
    page_count = 320
    published_date = dt.date(2020, 1, 1)
    published_date_precision = DatePrecision.YEAR

    @factory.post_generation
    def authors(self, create: bool, extracted: list[Author] | None, **kwargs) -> None:
        """BookFactory(authors=[a, b]) links authors in that credit order."""
        if not create or not extracted:
            return
        for position, author in enumerate(extracted):
            BookAuthor.objects.create(book=self, author=author, position=position)

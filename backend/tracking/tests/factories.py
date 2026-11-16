import datetime as dt

import factory

from accounts.tests.factories import UserFactory
from catalog.tests.factories import BookFactory
from tracking.models import ReadingLog, UserBook


class UserBookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserBook

    user = factory.SubFactory(UserFactory)
    book = factory.SubFactory(BookFactory)
    status = UserBook.Status.WANT_TO_READ

    class Params:
        # UserBookFactory(dnf=True) builds a valid DNF row.
        dnf = factory.Trait(
            status=UserBook.Status.DNF,
            dnf_page=80,
            dnf_at=dt.date(2026, 11, 1),
            dnf_reason=UserBook.DnfReason.PACING,
        )
        finished = factory.Trait(
            status=UserBook.Status.FINISHED,
            started_at=dt.date(2026, 10, 1),
            finished_at=dt.date(2026, 10, 20),
            rating=4,
        )


class ReadingLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReadingLog

    user = factory.SubFactory(UserFactory)
    book = factory.SubFactory(BookFactory)
    log_date = dt.date(2026, 11, 15)
    pages_read = 30

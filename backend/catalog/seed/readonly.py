"""A read-only database transaction, so a command that should only read can't write."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, transaction


@contextmanager
def read_only_transaction() -> Iterator[None]:
    """Everything inside runs in one Postgres READ ONLY transaction: any INSERT, UPDATE or
    DELETE fails with "cannot execute ... in a read-only transaction", and nothing is
    committed. Used by build_catalog_seed, which is run against production."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
        yield

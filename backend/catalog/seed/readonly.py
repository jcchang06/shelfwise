"""Keeping a command read-only against the database, without a long-lived transaction.

Neon terminates sessions that sit idle inside a transaction, so a build that held one
transaction open for ~6 minutes (reading dumps, calling Open Library) failed on COMMIT.
Instead:

- read_only_database(): for the whole block, this connection and any connection opened
  during it start every transaction READ ONLY (SET SESSION CHARACTERISTICS AS TRANSACTION
  READ ONLY, i.e. default_transaction_read_only = on). Any write fails.
- Read everything needed up front, in one short transaction, then release_connection()
  before the long work, so the build holds no connection at all while it runs.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection
from django.db.backends.signals import connection_created

_READ_ONLY_SESSION = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
_READ_WRITE_SESSION = "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"
_DISPATCH_UID = "catalog.seed.readonly"


def _make_read_only(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(_READ_ONLY_SESSION)
        if conn.in_atomic_block:
            # The session default only applies to new transactions; make the one already
            # open read-only too (tests run inside one).
            cursor.execute("SET TRANSACTION READ ONLY")


def _on_connect(sender, connection, **kwargs) -> None:
    _make_read_only(connection)


@contextmanager
def read_only_database() -> Iterator[None]:
    """Within the block, every transaction on this connection (and on any connection
    opened during it) is READ ONLY. Resets the session afterwards if still connected."""
    connection_created.connect(_on_connect, weak=False, dispatch_uid=_DISPATCH_UID)
    try:
        _make_read_only(connection)
        yield
    finally:
        connection_created.disconnect(dispatch_uid=_DISPATCH_UID)
        # Skipped when closed (nothing to reset) or when the transaction failed (a failed
        # write inside it): the rollback undoes the SET anyway.
        if connection.connection is not None and not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(_READ_WRITE_SESSION)


def release_connection(conn=connection) -> None:
    """Close the database connection before long work that doesn't need it, so no
    session sits idle on the server. Inside a transaction (tests) it's left alone."""
    if not conn.in_atomic_block:
        conn.close()

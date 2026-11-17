"""The data migration that moves imported placeholder DNFs to not_specified (T-6)."""

import importlib

import pytest
from django.apps import apps
from django.utils import timezone

from imports.models import GoodreadsLink
from tracking.models import UserBook
from tracking.tests.factories import UserBookFactory

migration = importlib.import_module("tracking.migrations.0003_imported_dnfs_not_specified")
R = UserBook.DnfReason
PLACEHOLDER = migration.PLACEHOLDER_NOTE

pytestmark = pytest.mark.django_db


def dnf(reason, note=""):
    return UserBookFactory(dnf=True, dnf_reason=reason, dnf_note=note)


def link(entry):
    GoodreadsLink.objects.create(
        user=entry.user, goodreads_book_id=str(entry.pk), user_book=entry, synced_at=timezone.now()
    )


def reasons(*entries):
    return [UserBook.objects.values_list("dnf_reason", "dnf_note").get(pk=e.pk) for e in entries]


def test_forwards_moves_only_the_exact_placeholder():
    placeholder = dnf(R.OTHER, PLACEHOLDER)
    real_other = dnf(R.OTHER, "Lost the thread")
    edited_note = dnf(R.OTHER, PLACEHOLDER + " — too slow")
    pacing = dnf(R.PACING, PLACEHOLDER)
    before = UserBook.objects.get(pk=placeholder.pk).updated_at

    migration.forwards(apps, None)

    assert reasons(placeholder, real_other, edited_note, pacing) == [
        (R.NOT_SPECIFIED, ""),
        (R.OTHER, "Lost the thread"),
        (R.OTHER, PLACEHOLDER + " — too slow"),
        (R.PACING, PLACEHOLDER),
    ]
    # Not "changed in Shelfwise since the last import" for a later re-import.
    assert UserBook.objects.get(pk=placeholder.pk).updated_at == before


def test_backwards_restores_the_placeholder_for_imported_dnfs():
    imported, by_hand = dnf(R.NOT_SPECIFIED), dnf(R.NOT_SPECIFIED)
    link(imported)

    migration.backwards(apps, None)

    assert reasons(imported, by_hand) == [(R.OTHER, PLACEHOLDER), (R.OTHER, "")]

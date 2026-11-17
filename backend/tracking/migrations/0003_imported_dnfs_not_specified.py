"""Imported DNFs used the placeholder reason "other" + note "Imported from Goodreads", since a
reason was required. The reason is optional now (T-6), so move them to not_specified and drop
the placeholder note. Only that exact pair changes; a note edited by hand is left alone.

QuerySet.update() skips auto_now, so updated_at is unchanged and these entries don't look
"changed in Shelfwise since the last import" to a later re-import (I-3).
"""

from django.db import migrations

PLACEHOLDER_NOTE = "Imported from Goodreads"


def forwards(apps, schema_editor):
    UserBook = apps.get_model("tracking", "UserBook")
    UserBook.objects.filter(status="dnf", dnf_reason="other", dnf_note=PLACEHOLDER_NOTE).update(
        dnf_reason="not_specified", dnf_note=""
    )


def backwards(apps, schema_editor):
    """Back to the old placeholder for imported DNFs; other blank reasons become "other"."""
    UserBook = apps.get_model("tracking", "UserBook")
    GoodreadsLink = apps.get_model("imports", "GoodreadsLink")
    unspecified = UserBook.objects.filter(dnf_reason="not_specified")
    imported = GoodreadsLink.objects.values("user_book_id")
    unspecified.filter(pk__in=imported, dnf_note="").update(
        dnf_reason="other", dnf_note=PLACEHOLDER_NOTE
    )
    unspecified.update(dnf_reason="other")


class Migration(migrations.Migration):
    dependencies = [
        ("tracking", "0002_dnf_reason_not_specified"),
        ("imports", "0001_initial"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]

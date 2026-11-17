"""Print which database manage.py is about to use, without the password.

Run it right before `migrate` when pointing at production, so you can see the host is
Neon and not local Postgres:

    python manage.py dbinfo && python manage.py migrate
"""

from django.core.management.base import BaseCommand
from django.db import connections


class Command(BaseCommand):
    help = "Show the database host, port, name and user (never the password)."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        db = connections[options["database"]].settings_dict
        host = db.get("HOST") or "(local socket)"
        port = f":{db['PORT']}" if db.get("PORT") else ""
        self.stdout.write(
            f"Database: {host}{port}/{db.get('NAME')} as {db.get('USER') or '(default user)'}"
        )

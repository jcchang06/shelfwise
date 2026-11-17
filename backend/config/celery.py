"""Celery app for LOCAL Docker only (the `worker` service in docker-compose.yml).

Production runs jobs as plain management commands from GitHub Actions, so this module is
never imported there (Celery isn't installed in production): start a worker with
`celery -A config.celery worker`.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("shelfwise")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

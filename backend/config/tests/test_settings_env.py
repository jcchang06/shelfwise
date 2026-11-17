"""Proves how settings.py resolves DATABASE_URL, by loading the real settings module in a
fresh process (module-level settings can't be re-imported inside the test process).

The README's deploy steps rely on this: with a local .env pointing at localhost,
`export DATABASE_URL=<neon>` must make manage.py talk to Neon.
"""

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.db import connections

BACKEND_DIR = Path(__file__).resolve().parents[2]

PRINT_DB = (
    "import django; django.setup(); from django.conf import settings; "
    "db = settings.DATABASES['default']; print(db['HOST'], db['NAME'], sep='|')"
)


def settings_db(env_file: Path, shell_database_url: str | None) -> tuple[str, str]:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_ENV_FILE": str(env_file),
        "DJANGO_SECRET_KEY": "test-only",
    }
    env.pop("DATABASE_URL", None)
    if shell_database_url is not None:
        env["DATABASE_URL"] = shell_database_url
    result = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-c", PRINT_DB],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    host, name = result.stdout.strip().split("|")
    return host, name


@pytest.fixture
def local_env_file(tmp_path) -> Path:
    path = tmp_path / ".env"
    path.write_text("DATABASE_URL=postgres://local:local@localhost:5432/shelfwise_local\n")
    return path


def test_shell_database_url_overrides_env_file(local_env_file):
    neon = "postgresql://u:p@ep-example.us-west-2.aws.neon.tech/neondb?sslmode=require"
    assert settings_db(local_env_file, neon) == ("ep-example.us-west-2.aws.neon.tech", "neondb")


def test_env_file_is_used_when_shell_has_none(local_env_file):
    assert settings_db(local_env_file, None) == ("localhost", "shelfwise_local")


def test_dbinfo_shows_host_but_never_the_password(monkeypatch):
    # The live connection holds its own copy of the settings, so patch that.
    connection = connections["default"]
    monkeypatch.setattr(
        connection,
        "settings_dict",
        {
            **connection.settings_dict,
            "HOST": "ep-example.us-west-2.aws.neon.tech",
            "PORT": 5432,
            "NAME": "neondb",
            "USER": "shelfwise_owner",
            "PASSWORD": "s3cret-value",
        },
    )
    out = StringIO()
    call_command("dbinfo", stdout=out)
    assert out.getvalue().strip() == (
        "Database: ep-example.us-west-2.aws.neon.tech:5432/neondb as shelfwise_owner"
    )
    assert "s3cret-value" not in out.getvalue()

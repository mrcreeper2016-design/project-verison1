"""Case-insensitive uniqueness for auth_user.email.

Postgres: create a unique functional index on LOWER(email) (skip empty).
Other engines (e.g. SQLite in dev): no-op. Application-level validation in
`accounts.forms` enforces uniqueness on write as a fallback.
"""
from django.db import migrations


CREATE_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS auth_user_email_lower_uniq "
    "ON auth_user (LOWER(email)) WHERE email <> '';"
)
DROP_SQL = "DROP INDEX IF EXISTS auth_user_email_lower_uniq;"


def _run_if_postgres(forward):
    def wrapped(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(forward)
    return wrapped


class Migration(migrations.Migration):

    atomic = False  # CREATE INDEX does not need a transaction; safer for large tables

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            _run_if_postgres(CREATE_SQL),
            reverse_code=_run_if_postgres(DROP_SQL),
        ),
    ]

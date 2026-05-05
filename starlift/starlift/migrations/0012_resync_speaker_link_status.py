# Normalizes legacy status values (e.g. "parsed") after imports or pre-migration rows.

from django.db import migrations


def sync_speaker_auth_status(apps, schema_editor):
    Speaker = apps.get_model("starlift", "Speaker")
    Speaker.objects.exclude(user_id__isnull=True).update(status="authorized")
    Speaker.objects.filter(user_id__isnull=True).update(status="unauthorized")


class Migration(migrations.Migration):

    dependencies = [
        ("starlift", "0011_speaker_auth_status"),
    ]

    operations = [
        migrations.RunPython(sync_speaker_auth_status, migrations.RunPython.noop),
    ]

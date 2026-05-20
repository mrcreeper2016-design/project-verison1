"""Backfill UserProfile rows for users that already exist.

Superusers and staff users become admins (and are marked email_verified so
they can operate the system right after the migration lands); regular users
become speakers.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("accounts", "UserProfile")

    for user in User.objects.all().iterator():
        role = "admin" if (user.is_superuser or user.is_staff) else "speaker"
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                "role": role,
                "email_verified": bool(user.is_superuser),
                "bio": "",
            },
        )


def backwards(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    UserProfile.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_auth_user_email_lower_index"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

from django.db import migrations


def backfill_consent(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    profiles = UserProfile.objects.select_related("user").filter(
        pdn_consent_at__isnull=True
    )
    for profile in profiles.iterator():
        joined = profile.user.date_joined
        profile.pdn_consent_at = joined
        profile.policy_accepted_at = joined
        profile.consent_doc_version = "legacy"
        profile.save(update_fields=[
            "pdn_consent_at",
            "policy_accepted_at",
            "consent_doc_version",
        ])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_userprofile_consent_doc_version_and_more"),
    ]
    operations = [
        migrations.RunPython(backfill_consent, noop_reverse),
    ]

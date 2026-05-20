from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import UserProfile
from starlift.models import Speaker


class Command(BaseCommand):
    help = "Migrate legacy /media avatar paths to object storage-backed ImageField."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be migrated without writing.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing avatar field values.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        if not getattr(settings, "USE_OBJECT_STORAGE", False):
            self.stdout.write(
                self.style.WARNING(
                    "USE_OBJECT_STORAGE is disabled. Migration is expected to run with object storage enabled."
                )
            )

        media_root = Path(settings.MEDIA_ROOT)
        total = migrated = skipped = missing = errors = 0

        speaker_qs = Speaker.objects.all().order_by("id")
        for speaker in speaker_qs.iterator():
            if not speaker.img or not speaker.img.startswith("/media/"):
                continue

            total += 1
            if speaker.avatar and not force:
                skipped += 1
                self.stdout.write(f"SKIP speaker#{speaker.pk}: avatar already set")
                continue

            rel_path = speaker.img[len("/media/") :].lstrip("/\\")
            source_path = media_root / rel_path
            if not source_path.exists():
                missing += 1
                self.stdout.write(self.style.WARNING(f"MISS speaker#{speaker.pk}: {source_path}"))
                continue

            self.stdout.write(f"MIGRATE speaker#{speaker.pk}: {source_path}")
            if dry_run:
                continue

            try:
                with source_path.open("rb") as fh:
                    upload_name = source_path.name
                    with transaction.atomic():
                        speaker.avatar.save(upload_name, File(fh), save=False)
                        speaker.save(update_fields=["avatar"])
                migrated += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                errors += 1
                self.stdout.write(self.style.ERROR(f"ERR speaker#{speaker.pk}: {exc}"))

        profiles_with_avatar = (
            UserProfile.objects.filter(avatar__isnull=False).exclude(avatar="").count()
        )

        self.stdout.write("")
        self.stdout.write(f"Scanned legacy speaker avatars: {total}")
        self.stdout.write(self.style.SUCCESS(f"Migrated: {migrated}"))
        self.stdout.write(f"Skipped: {skipped}")
        self.stdout.write(f"User profiles with avatar already set: {profiles_with_avatar}")
        self.stdout.write(self.style.WARNING(f"Missing local files: {missing}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors: {errors}"))
        else:
            self.stdout.write("Errors: 0")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run mode; no writes performed."))

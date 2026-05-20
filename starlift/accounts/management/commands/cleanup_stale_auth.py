"""Periodic cleanup of expired auth artefacts.

Run daily from cron/scheduler:

    python manage.py cleanup_stale_auth

Scope:
- Expired + unused invites (marks as revoked_at=now for auditability).
- Expired email-verification records (marks as used_at=now to retire them).
- LoginAttempt rows older than N days (default 30).

Never deletes AuditLog entries — those are retained per policy.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import EmailVerification, Invite, LoginAttempt


class Command(BaseCommand):
    help = "Purge expired invites / email-verification tokens and old login-attempt rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--login-attempt-days",
            type=int,
            default=30,
            help="Delete login attempts older than this many days (default: 30).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing.",
        )

    def handle(self, *args, **opts):
        now = timezone.now()
        dry = opts["dry_run"]

        expired_invites = Invite.objects.filter(
            used_at__isnull=True, revoked_at__isnull=True, expires_at__lte=now
        )
        stale_verifs = EmailVerification.objects.filter(used_at__isnull=True, expires_at__lte=now)
        cutoff = now - timedelta(days=opts["login_attempt_days"])
        old_attempts = LoginAttempt.objects.filter(created_at__lt=cutoff)

        ci = expired_invites.count()
        cv = stale_verifs.count()
        ca = old_attempts.count()

        self.stdout.write(f"Expired invites to mark revoked: {ci}")
        self.stdout.write(f"Stale email verifications to retire: {cv}")
        self.stdout.write(f"Old login attempts to delete (>{opts['login_attempt_days']}d): {ca}")

        if dry:
            self.stdout.write(self.style.WARNING("Dry run; no changes written."))
            return

        if ci:
            expired_invites.update(revoked_at=now)
        if cv:
            stale_verifs.update(used_at=now)
        if ca:
            old_attempts.delete()

        self.stdout.write(self.style.SUCCESS("Cleanup complete."))

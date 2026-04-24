"""Username-scoped brute-force lockout.

Policy: after N failed attempts in the last W seconds (defaults 6/60),
further attempts by that username are refused without checking the
password. A successful login clears the failure counter.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from ..models import AuditLog, LoginAttempt
from . import audit


def _window() -> timedelta:
    return timedelta(seconds=settings.ACCOUNTS_LOCKOUT_WINDOW_SECONDS)


def _threshold() -> int:
    return settings.ACCOUNTS_LOCKOUT_THRESHOLD


def _normalize(username: str) -> str:
    return (username or "").strip().lower()


def recent_failures(username: str):
    now = timezone.now()
    return LoginAttempt.objects.filter(
        username_or_email=_normalize(username),
        success=False,
        created_at__gte=now - _window(),
    )


def is_locked(username: str) -> bool:
    if not username:
        return False
    return recent_failures(username).count() >= _threshold()


def seconds_until_unlock(username: str) -> int:
    latest = recent_failures(username).aggregate(latest=Max("created_at")).get("latest")
    if not latest:
        return 0
    elapsed = (timezone.now() - latest).total_seconds()
    remaining = settings.ACCOUNTS_LOCKOUT_WINDOW_SECONDS - int(elapsed)
    return max(0, remaining)


def register_attempt(username: str, ip: Optional[str], success: bool) -> LoginAttempt:
    attempt = LoginAttempt.objects.create(
        username_or_email=_normalize(username),
        ip=ip,
        success=bool(success),
    )
    if success:
        # Clear prior failures for this account on success to avoid stale locks.
        LoginAttempt.objects.filter(
            username_or_email=_normalize(username),
            success=False,
        ).delete()
    return attempt


def unlock(username: str, *, actor=None, request=None) -> int:
    """Admin-triggered unlock. Removes failures in the current window and audits."""
    deleted, _ = recent_failures(username).delete()
    audit.log(
        action=AuditLog.ACTION_LOCKOUT_LIFTED,
        actor=actor,
        request=request,
        target_type="Username",
        target_id=_normalize(username),
        metadata={"removed_failures": deleted},
    )
    return deleted

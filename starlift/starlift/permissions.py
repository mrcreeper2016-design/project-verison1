"""Shared role and ownership helpers used across the starlift views.

Single source of truth so ``views.py`` and ``views_me.py`` don't each carry
their own copy of the same role check / speaker lookup.
"""
from __future__ import annotations

from .models import Speaker


def is_platform_admin(user) -> bool:
    """True for a superuser or a staff-level role (admin / devrel)."""
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role in ("admin", "devrel"))


def get_speaker_for_user(user):
    """Return the Speaker card linked to ``user``, or ``None``."""
    return Speaker.objects.filter(user=user).first()

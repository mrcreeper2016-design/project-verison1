"""Resolve avatar URL for a user (mirror of accounts.context_processors).

Order: UserProfile.avatar → linked Speaker.card_avatar_url → empty string.
Used by support views to attach avatars to messages without a request.
"""
from __future__ import annotations

from accounts.models import UserProfile


def avatar_url_for_user(user) -> str:
    if user is None:
        return ""
    try:
        prof = user.profile
    except UserProfile.DoesNotExist:
        prof = None
    if prof and prof.avatar and getattr(prof.avatar, "name", ""):
        try:
            return prof.avatar.url
        except ValueError:
            pass
    try:
        sp = user.speaker
    except Exception:
        return ""
    return getattr(sp, "card_avatar_url", "") or ""

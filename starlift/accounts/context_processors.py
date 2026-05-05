"""Template extras."""

from __future__ import annotations

from accounts.models import UserProfile
from starlift.models import Speaker


def header_avatar_url(request):
    """Shell avatar: загруженный в аккаунт файл; иначе фото с карточки спикера (в т.ч. спарсенное)."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"header_avatar_url": ""}

    user = request.user
    try:
        prof = user.profile
    except UserProfile.DoesNotExist:
        prof = None
    if prof and prof.avatar and getattr(prof.avatar, "name", ""):
        try:
            return {"header_avatar_url": prof.avatar.url}
        except ValueError:
            pass

    try:
        sp = user.speaker
    except Speaker.DoesNotExist:
        return {"header_avatar_url": ""}
    return {"header_avatar_url": sp.card_avatar_url or ""}

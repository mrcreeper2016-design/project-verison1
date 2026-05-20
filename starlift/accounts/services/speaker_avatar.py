"""Keep one photo for a linked speaker: profile ``UserProfile.avatar`` after link and edits."""
from __future__ import annotations

import os
import re
import uuid
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.base import ContentFile

from accounts.models import UserProfile

_IMG_NUM = re.compile(r"^\d{1,3}$")


def _guess_ext_from_content_type(ct: str) -> str:
    ct = (ct or "").lower()
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    return ".jpg"


def _profile_for_user(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def backfill_profile_avatar_if_empty(speaker, user) -> bool:
    """If the user has no profile photo yet, copy the speaker card image into the profile (one-time fix)."""
    profile = _profile_for_user(user)
    if profile.avatar and getattr(profile.avatar, "name", ""):
        return False
    return seed_user_profile_avatar_from_linked_speaker(speaker, user)


def seed_user_profile_avatar_from_linked_speaker(speaker, user) -> bool:
    """After admin/invite links ``speaker`` → ``user``, copy the card photo into ``UserProfile.avatar``.

    Overwrites an existing profile avatar so the parsed/card image is the single source going forward.
    Returns True if the profile image was set or replaced.
    """
    profile = _profile_for_user(user)
    updated = False

    if getattr(speaker, "avatar", None) and speaker.avatar:
        try:
            with speaker.avatar.open("rb") as src:
                raw = src.read()
            base = os.path.basename(speaker.avatar.name) or "speaker.jpg"
            _, ext = os.path.splitext(base)
            if not ext:
                ext = ".webp"
            name = f"linked_{uuid.uuid4().hex[:10]}{ext}"
            profile.avatar.save(name, ContentFile(raw), save=False)
            updated = True
        except OSError:
            pass
    elif (speaker.img or "").strip():
        updated = _import_img_string_to_profile((speaker.img or "").strip(), profile)

    if updated:
        profile.save(update_fields=["avatar", "updated_at"])
    return updated


def _import_img_string_to_profile(img: str, profile: UserProfile) -> bool:
    """Set profile.avatar from ``Speaker.img`` (URL, /media/… path, or pravatar id)."""
    if img.startswith(("http://", "https://")):
        return _download_url_to_profile(img, profile)
    media_url = (getattr(settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/") + "/"
    if img.startswith(media_url) or img.startswith("/media/"):
        rel = img.split("/media/", 1)[-1].lstrip("/")
        path = os.path.join(str(settings.MEDIA_ROOT), rel)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    _, ext = os.path.splitext(path)
                    ext = ext or ".jpg"
                    profile.avatar.save(f"linked_{uuid.uuid4().hex[:10]}{ext}", ContentFile(fh.read()), save=False)
                return True
            except OSError:
                return False
    if _IMG_NUM.fullmatch(img):
        url = f"https://i.pravatar.cc/512?img={img}"
        return _download_url_to_profile(url, profile)
    return False


def _download_url_to_profile(url: str, profile: UserProfile) -> bool:
    try:
        req = Request(url, headers={"User-Agent": "StarliftAvatarSync/1.0"})
        with urlopen(req, timeout=25) as resp:  # noqa: S310 — intentional URL from our own data
            data = resp.read()
            ext = _guess_ext_from_content_type(resp.headers.get("Content-Type", ""))
            profile.avatar.save(f"linked_{uuid.uuid4().hex[:10]}{ext}", ContentFile(data), save=False)
        return True
    except (URLError, OSError, ValueError):
        return False


def mirror_speaker_uploaded_avatar_to_profile(speaker) -> bool:
    """After the speaker uploads an image on the card, copy ``Speaker.avatar`` to the linked profile."""
    uid = getattr(speaker, "user_id", None)
    if not uid or not getattr(speaker, "avatar", None) or not speaker.avatar:
        return False
    user = speaker.user
    profile = _profile_for_user(user)
    try:
        with speaker.avatar.open("rb") as src:
            raw = src.read()
        base = os.path.basename(speaker.avatar.name) or "speaker.jpg"
        _, ext = os.path.splitext(base)
        ext = ext or ".webp"
        name = f"card_{uuid.uuid4().hex[:10]}{ext}"
        profile.avatar.save(name, ContentFile(raw), save=False)
    except OSError:
        return False
    profile.save(update_fields=["avatar", "updated_at"])
    return True

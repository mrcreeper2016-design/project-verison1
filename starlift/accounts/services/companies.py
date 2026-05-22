"""Helpers for collecting unique company names across the platform.

Used to power the `<datalist>` autocomplete on every form where a user
enters a company (DevRel zone, applicant company, speaker card).
"""
from __future__ import annotations


def get_company_suggestions(limit: int = 200) -> list[str]:
    """Return distinct non-empty company names sorted alphabetically.

    Sources: UserProfile.company, SpeakerApplication.company, Speaker.sub
    (the canonical company field on a speaker card).
    """
    # Deferred imports to avoid app-loading cycles.
    from accounts.models import UserProfile
    from starlift.models import Speaker, SpeakerApplication

    names: set[str] = set()
    for value in UserProfile.objects.exclude(company="").values_list("company", flat=True):
        s = (value or "").strip()
        if s:
            names.add(s)
    for value in SpeakerApplication.objects.exclude(company="").values_list("company", flat=True):
        s = (value or "").strip()
        if s:
            names.add(s)
    for value in Speaker.objects.exclude(sub="").values_list("sub", flat=True):
        s = (value or "").strip()
        if s:
            names.add(s)

    return sorted(names, key=str.lower)[:limit]

"""Speaker-related read-only tools for the assistant."""
from __future__ import annotations

from django.db.models import Q

from accounts.models import UserProfile
from starlift.models import Speaker

from . import assistant_tool


def _role(user) -> str:
    try:
        return user.profile.role
    except (UserProfile.DoesNotExist, AttributeError):
        return UserProfile.ROLE_GUEST


def _scope_for(user):
    qs = Speaker.objects.all()
    if _role(user) == UserProfile.ROLE_SPEAKER:
        qs = qs.filter(user=user)
    return qs


@assistant_tool(
    name="search_speakers",
    description=(
        "Search for speaker cards. Supports filtering by free-text query "
        "(matches name or bio), tech stack substring, city, and minimum NPS. "
        "Returns compact list."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search across name and bio."},
            "stack": {"type": "string", "description": "Tech stack substring, e.g. 'Python'."},
            "city": {"type": "string"},
            "nps_min": {"type": "integer", "minimum": 0, "maximum": 100},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        },
    },
)
def search_speakers(*, query="", stack="", city="", nps_min=None, limit=10, _user=None):
    qs = _scope_for(_user)
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(bio__icontains=query))
    if stack:
        qs = qs.filter(stack__icontains=stack)
    if city:
        qs = qs.filter(city__iexact=city)
    if nps_min is not None:
        qs = qs.filter(nps__gte=nps_min)
    qs = qs.order_by("-nps", "name")[: max(1, min(int(limit), 10))]
    return {
        "speakers": [
            {
                "id": s.id,
                "name": s.name,
                "stack": s.stack or "",
                "city": s.city or "",
                "nps": s.nps,
            }
            for s in qs
        ]
    }


@assistant_tool(
    name="get_speaker_profile",
    description="Get a single speaker's full profile (truncated bio, NPS, stack).",
    parameters={
        "type": "object",
        "properties": {"speaker_id": {"type": "integer"}},
        "required": ["speaker_id"],
    },
)
def get_speaker_profile(*, speaker_id, _user=None):
    qs = _scope_for(_user)
    s = qs.filter(id=speaker_id).first()
    if not s:
        return {"error": "not_found"}
    bio = (s.bio or "")[:500]
    return {
        "id": s.id,
        "name": s.name,
        "stack": s.stack or "",
        "city": s.city or "",
        "sub": s.sub or "",
        "bio": bio,
        "nps": s.nps,
        "status": s.status,
    }

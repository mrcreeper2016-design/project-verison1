"""Event-related read-only tools for the assistant."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from starlift.models import Event

from . import assistant_tool


@assistant_tool(
    name="find_events",
    description=(
        "Find events. By default returns upcoming events sorted by date. "
        "Supports filtering by topic substring, location, external flag, "
        "and time window (period_days)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "location": {"type": "string"},
            "is_external": {"type": "boolean"},
            "period_days": {
                "type": "integer",
                "description": "Look ahead this many days. 0 means upcoming with no upper bound.",
                "minimum": 0,
                "maximum": 365,
                "default": 0,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        },
    },
)
def find_events(*, topic="", location="", is_external=None, period_days=0, limit=10, _user=None):
    today = timezone.now().date()
    qs = Event.objects.filter(
        Q(event_date__gte=today) | Q(event_date__isnull=True, status="future")
    )
    if topic:
        qs = qs.filter(Q(topic__icontains=topic) | Q(speakers__stack__icontains=topic))
    if location:
        qs = qs.filter(location__icontains=location)
    if is_external is not None:
        qs = qs.filter(is_external=is_external)
    if period_days:
        qs = qs.filter(event_date__lte=today + timedelta(days=period_days))
    qs = qs.distinct().order_by("event_date", "id")[: max(1, min(int(limit), 10))]
    return {
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "date": e.event_date.isoformat() if e.event_date else (e.date or ""),
                "topic": e.topic or "",
                "location": e.location or "",
            }
            for e in qs
        ]
    }


@assistant_tool(
    name="get_event_details",
    description="Get one event with its speakers and key fields.",
    parameters={
        "type": "object",
        "properties": {"event_id": {"type": "integer"}},
        "required": ["event_id"],
    },
)
def get_event_details(*, event_id, _user=None):
    e = Event.objects.filter(id=event_id).prefetch_related("speakers").first()
    if not e:
        return {"error": "not_found"}
    return {
        "id": e.id,
        "title": e.title,
        "date": e.event_date.isoformat() if e.event_date else (e.date or ""),
        "topic": e.topic or "",
        "location": e.location or "",
        "is_external": bool(e.is_external),
        "description": (e.description or "")[:500],
        "speakers": [
            {"id": s.id, "name": s.name, "nps": s.nps}
            for s in e.speakers.all()[:10]
        ],
    }

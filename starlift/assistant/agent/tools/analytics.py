"""Analytics tools."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone

from accounts.models import UserProfile
from starlift.models import Feedback

from . import assistant_tool

PROMOTER_MIN = 9
DETRACTOR_MAX = 6


@assistant_tool(
    name="nps_summary",
    description=(
        "Aggregate NPS for the given window. Optional speaker_id or event_id "
        "narrows the scope. Returns total, promoters, detractors, NPS, avg_score."
    ),
    parameters={
        "type": "object",
        "properties": {
            "period_days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
            "speaker_id": {"type": "integer"},
            "event_id": {"type": "integer"},
        },
    },
)
def nps_summary(*, period_days=30, speaker_id=None, event_id=None, _user=None):
    since = timezone.now() - timedelta(days=int(period_days))
    qs = Feedback.objects.filter(created_at__gte=since)
    if speaker_id:
        qs = qs.filter(speaker_id=speaker_id)
    if event_id:
        qs = qs.filter(event_id=event_id)

    try:
        role = _user.profile.role if _user else UserProfile.ROLE_GUEST
    except (UserProfile.DoesNotExist, AttributeError):
        role = UserProfile.ROLE_GUEST

    if role == UserProfile.ROLE_SPEAKER:
        qs = qs.filter(speaker__user=_user)

    stats = qs.aggregate(
        total=Count("id"),
        promoters=Count("id", filter=Q(score__gte=PROMOTER_MIN)),
        detractors=Count("id", filter=Q(score__lte=DETRACTOR_MAX)),
        avg=Avg("score"),
    )
    total = stats["total"] or 0
    promoters = stats["promoters"] or 0
    detractors = stats["detractors"] or 0
    nps = ((promoters - detractors) / total * 100) if total else 0.0
    return {
        "period_days": int(period_days),
        "total": total,
        "promoters": promoters,
        "detractors": detractors,
        "nps": round(nps, 1),
        "avg_score": round(stats["avg"] or 0, 2),
    }

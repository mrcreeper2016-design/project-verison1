"""Service layer for the Home dashboard.

All aggregations happen in SQL via ORM annotations and are post-processed in
pure Python so the pieces are easy to unit-test. This module is consumed by:

* ``views.index_view``  — initial template render (options for filter dropdowns);
* ``views.home_api``    — lightweight JSON endpoint polled by the page.

Design goals:

* Defensive against empty/NULL data (brand new DB should not crash).
* No N+1: ``select_related`` / ``prefetch_related`` / annotated aggregates.
* Single ``data_version`` hash so the frontend can cheaply skip re-rendering
  when nothing has changed (prevents visual flicker on each poll).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import blake2s
from typing import Any

from django.db.models import Avg, Count, F, Max, Q
from django.utils import timezone

from . import analytics as analytics_lib
from .models import Event, Feedback, Speaker

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PERIOD_DAYS = 30
ALLOWED_PERIODS = (30, 90, 180)
NEW_SPEAKER_WINDOW_DAYS = 30

UPCOMING_LIMIT = 6
TOP_SPEAKERS_LIMIT = 5
ACTIVITY_LIMIT = 10
ACTIVITY_WINDOW_DAYS = 60


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HomeFilters:
    period: str
    city: str
    topic: str
    nps_threshold: float | None
    start_dt: datetime
    end_dt: datetime


def parse_filters(get_params) -> HomeFilters:
    raw_period = (get_params.get("period") or str(DEFAULT_PERIOD_DAYS)).strip()
    try:
        days = int(raw_period)
    except (TypeError, ValueError):
        days = DEFAULT_PERIOD_DAYS
    if days not in ALLOWED_PERIODS:
        # Guard against arbitrary values without hard-failing.
        days = min(ALLOWED_PERIODS, key=lambda x: abs(x - days))

    city = (get_params.get("city") or "").strip()
    topic = (get_params.get("topic") or "").strip()

    raw_threshold = (get_params.get("nps_threshold") or "").strip()
    try:
        nps_threshold = float(raw_threshold.replace(",", ".")) if raw_threshold else None
    except ValueError:
        nps_threshold = None

    now = timezone.now()
    return HomeFilters(
        period=str(days),
        city=city,
        topic=topic,
        nps_threshold=nps_threshold,
        start_dt=now - timedelta(days=days),
        end_dt=now,
    )


def _as_analytics_filters(filters: HomeFilters) -> analytics_lib.AnalyticsFilters:
    return analytics_lib.AnalyticsFilters(
        period=filters.period,
        city=filters.city,
        topic=filters.topic,
        nps_threshold=filters.nps_threshold,
    )


# ---------------------------------------------------------------------------
# Queryset helpers
# ---------------------------------------------------------------------------

def _feedbacks_in_window(filters: HomeFilters):
    qs = Feedback.objects.select_related("speaker", "event").filter(
        created_at__gte=filters.start_dt,
        created_at__lte=filters.end_dt,
    )
    if filters.city:
        qs = qs.filter(speaker__city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(
            Q(speaker__stack__icontains=filters.topic) | Q(event__topic__icontains=filters.topic)
        )
    return qs


def _events_in_window(filters: HomeFilters):
    start = filters.start_dt
    end = filters.end_dt
    qs = Event.objects.filter(
        Q(event_date__gte=start.date(), event_date__lte=end.date())
        | Q(event_date__isnull=True, feedbacks__created_at__gte=start, feedbacks__created_at__lte=end)
    ).distinct()
    if filters.topic:
        qs = qs.filter(
            Q(topic__icontains=filters.topic) | Q(speakers__stack__icontains=filters.topic)
        ).distinct()
    if filters.city:
        qs = qs.filter(speakers__city__iexact=filters.city).distinct()
    return qs


def _speakers_scope(filters: HomeFilters):
    qs = Speaker.objects.all()
    if filters.city:
        qs = qs.filter(city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(stack__icontains=filters.topic)
    return qs


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def compute_kpis(filters: HomeFilters) -> dict[str, Any]:
    speaker_scope = _speakers_scope(filters)
    feedbacks_in_window = _feedbacks_in_window(filters)

    total_speakers = speaker_scope.count()
    active_speakers = feedbacks_in_window.values("speaker_id").distinct().count()
    events_in_period = _events_in_window(filters).count()

    new_speakers_since = timezone.now() - timedelta(days=NEW_SPEAKER_WINDOW_DAYS)
    new_speakers = speaker_scope.filter(created_at__gte=new_speakers_since).count()

    nps_stats = analytics_lib.compute_nps(feedbacks_in_window)

    # Candidates follow the project rule (≥9.4 avg, ≥2 events in 180d, flag).
    candidates = analytics_lib.nomination_candidates(_as_analytics_filters(filters))

    return {
        "total_speakers": total_speakers,
        "active_speakers": active_speakers,
        "events_in_period": events_in_period,
        "avg_nps": nps_stats["nps"],
        "avg_score": nps_stats["avg_score"],
        "total_feedbacks": nps_stats["total"],
        "candidates_count": len(candidates),
        "new_speakers": new_speakers,
        "window_days": int(filters.period),
    }


def upcoming_events(filters: HomeFilters, limit: int = UPCOMING_LIMIT) -> list[dict[str, Any]]:
    today = timezone.now().date()

    # Primary: event_date today or in the future.
    # Fallback: events without event_date but explicitly marked status='future'.
    qs = Event.objects.filter(
        Q(event_date__gte=today) | Q(event_date__isnull=True, status="future")
    )
    if filters.city:
        qs = qs.filter(speakers__city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(
            Q(topic__icontains=filters.topic) | Q(speakers__stack__icontains=filters.topic)
        )
    qs = (
        qs.distinct()
        .annotate(speakers_count=Count("speakers", distinct=True))
        .order_by(F("event_date").asc(nulls_last=True), "id")
    )

    items: list[dict[str, Any]] = []
    for ev in qs[:limit]:
        description = (ev.description or "").strip()
        if len(description) > 160:
            description = description[:157] + "…"
        items.append({
            "id": ev.id,
            "title": ev.title,
            "date_iso": ev.event_date.isoformat() if ev.event_date else None,
            "date_label": ev.event_date.strftime("%d.%m.%Y") if ev.event_date else (ev.date or ""),
            "location": ev.location or "",
            "description": description,
            "status": ev.status or "future",
            "topic": ev.topic or "",
            "is_external": bool(ev.is_external),
            "speakers_count": ev.speakers_count or 0,
            "link": ev.link or "",
        })
    return items


def top_speakers(filters: HomeFilters, limit: int = TOP_SPEAKERS_LIMIT) -> list[dict[str, Any]]:
    window_filter = Q(
        feedbacks__created_at__gte=filters.start_dt,
        feedbacks__created_at__lte=filters.end_dt,
    )

    qs = _speakers_scope(filters).annotate(
        feedbacks_window=Count("feedbacks", filter=window_filter),
        avg_score_window=Avg("feedbacks__score", filter=window_filter),
        promoters=Count(
            "feedbacks",
            filter=window_filter & Q(feedbacks__score__gte=analytics_lib.PROMOTER_MIN_SCORE),
        ),
        detractors=Count(
            "feedbacks",
            filter=window_filter & Q(feedbacks__score__lte=analytics_lib.DETRACTOR_MAX_SCORE),
        ),
        events_window=Count("feedbacks__event", filter=window_filter, distinct=True),
    ).filter(feedbacks_window__gt=0)

    if filters.nps_threshold is not None:
        qs = qs.filter(avg_score_window__gte=filters.nps_threshold)

    qs = qs.order_by("-avg_score_window", "-feedbacks_window", "-promoters")[:limit]

    result: list[dict[str, Any]] = []
    for sp in qs:
        total = sp.feedbacks_window or 0
        avg = sp.avg_score_window
        result.append({
            "id": sp.id,
            "name": sp.name,
            "sub": sp.sub,
            "stack": sp.stack,
            "city": sp.city,
            "avatar": sp.avatar_url,
            "nps": round(avg, 1) if avg is not None else 0.0,
            "avg_score": round(avg, 2) if avg is not None else None,
            "feedbacks_count": total,
            "events_count": sp.events_window or 0,
            "recommended": bool(sp.recommended),
        })
    return result


def activity_feed(limit: int = ACTIVITY_LIMIT) -> list[dict[str, Any]]:
    """Unified activity stream aggregated from real entities.

    Speakers and Events use ``created_at`` (added in migration 0008). Rows
    created before that migration have NULL and are therefore excluded — we
    only surface real, dated activity.
    """
    window_start = timezone.now() - timedelta(days=ACTIVITY_WINDOW_DAYS)
    items: list[dict[str, Any]] = []

    feedback_rows = (
        Feedback.objects.select_related("speaker", "event")
        .filter(created_at__gte=window_start)
        .order_by("-created_at")[:limit]
    )
    for fb in feedback_rows:
        items.append({
            "type": "feedback",
            "icon": "fa-comment-dots",
            "timestamp": fb.created_at.isoformat(),
            "title": f"Новый отзыв · {fb.score}/10",
            "subtitle": f"{fb.speaker.name} — {fb.event.title}",
            "speaker_id": fb.speaker_id,
        })

    speaker_rows = (
        Speaker.objects.filter(created_at__isnull=False, created_at__gte=window_start)
        .order_by("-created_at")[:limit]
    )
    for sp in speaker_rows:
        items.append({
            "type": "speaker",
            "icon": "fa-user-plus",
            "timestamp": sp.created_at.isoformat(),
            "title": f"Добавлен спикер {sp.name}",
            "subtitle": (sp.stack or "").strip() or (sp.city or ""),
            "speaker_id": sp.id,
        })

    event_rows = (
        Event.objects.filter(created_at__isnull=False, created_at__gte=window_start)
        .order_by("-created_at")[:limit]
    )
    for ev in event_rows:
        items.append({
            "type": "event",
            "icon": "fa-calendar-plus",
            "timestamp": ev.created_at.isoformat(),
            "title": f"Новое мероприятие «{ev.title}»",
            "subtitle": ev.location or ev.topic or "",
            "speaker_id": None,
        })

    items.sort(key=lambda row: row["timestamp"], reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Filter dropdown options
# ---------------------------------------------------------------------------

def filter_options() -> dict[str, list[str]]:
    cities = sorted({
        (c or "").strip()
        for c in Speaker.objects.values_list("city", flat=True)
        if (c or "").strip()
    })
    topics = sorted({
        t
        for stack in Speaker.objects.values_list("stack", flat=True)
        for t in analytics_lib._split_topics(stack)
    })
    return {"cities": cities, "topics": topics}


# ---------------------------------------------------------------------------
# Data version — cheap change detection for polling
# ---------------------------------------------------------------------------

def data_version() -> str:
    """Short hex digest that only changes when underlying data changes.

    We combine row counts and the latest mutation timestamp for each of the
    three entities the dashboard reads. The frontend compares this value
    across polls and skips DOM updates when it hasn't moved, which gives us a
    flicker-free soft refresh.
    """
    fb = Feedback.objects.aggregate(cnt=Count("id"), last=Max("created_at"))
    sp = Speaker.objects.aggregate(cnt=Count("id"), last=Max("created_at"))
    ev = Event.objects.aggregate(cnt=Count("id"), last=Max("created_at"))

    parts = [
        str(fb["cnt"] or 0),
        fb["last"].isoformat() if fb["last"] else "",
        str(sp["cnt"] or 0),
        sp["last"].isoformat() if sp["last"] else "",
        str(ev["cnt"] or 0),
        ev["last"].isoformat() if ev["last"] else "",
    ]
    return blake2s("|".join(parts).encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------

def build_home(filters: HomeFilters) -> dict[str, Any]:
    return {
        "version": data_version(),
        "generated_at": timezone.now().isoformat(),
        "filters": {
            "period": filters.period,
            "city": filters.city,
            "topic": filters.topic,
            "nps_threshold": filters.nps_threshold,
        },
        "options": filter_options(),
        "kpis": compute_kpis(filters),
        "upcoming_events": upcoming_events(filters),
        "top_speakers": top_speakers(filters),
        "activity": activity_feed(),
    }

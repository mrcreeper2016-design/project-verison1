"""Analytics helpers for the StarLift dashboard.

All aggregations are performed at the ORM level and then post-processed in pure
Python so individual pieces are easy to unit-test. Nothing here renders HTML —
this module returns plain dicts/lists that the view passes into the template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from django.db.models import Avg, Count, F, Q, QuerySet
from django.utils import timezone

from .models import Event, Feedback, Speaker


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROMOTER_MIN_SCORE = 9
DETRACTOR_MAX_SCORE = 6

DEFAULT_PERIOD_DAYS = 90
CANDIDATE_WINDOW_DAYS = 180  # "последние полгода"
CANDIDATE_MIN_EVENTS = 2
CANDIDATE_MIN_AVG_SCORE = 9.4

PERIOD_PRESETS = (
    ("30", "30 дней"),
    ("90", "90 дней"),
    ("180", "180 дней"),
    ("custom", "Свой диапазон"),
)


# ---------------------------------------------------------------------------
# Filter parsing
# ---------------------------------------------------------------------------

@dataclass
class AnalyticsFilters:
    """Sanitised filter state derived from request GET params."""

    period: str = str(DEFAULT_PERIOD_DAYS)
    city: str = ""
    topic: str = ""
    nps_threshold: float | None = None
    date_from: date | None = None
    date_to: date | None = None
    only_recommended: bool = False

    # Resolved window in timezone-aware datetimes.
    start_dt: datetime = field(init=False)
    end_dt: datetime = field(init=False)

    def __post_init__(self) -> None:
        now = timezone.now()
        if self.period == "custom" and (self.date_from or self.date_to):
            start = self.date_from or (now.date() - timedelta(days=DEFAULT_PERIOD_DAYS))
            end = self.date_to or now.date()
            self.start_dt = _start_of_day(start)
            self.end_dt = _end_of_day(end)
        else:
            try:
                days = int(self.period)
            except (TypeError, ValueError):
                days = DEFAULT_PERIOD_DAYS
            days = max(1, min(days, 3650))
            self.end_dt = now
            self.start_dt = now - timedelta(days=days)

    # ---- serialisation for templates ------------------------------------
    def as_context(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "city": self.city,
            "topic": self.topic,
            "nps_threshold": self.nps_threshold if self.nps_threshold is not None else "",
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "only_recommended": self.only_recommended,
            "start_date": self.start_dt.date().isoformat(),
            "end_date": self.end_dt.date().isoformat(),
            "period_presets": PERIOD_PRESETS,
        }


def parse_filters(get_params) -> AnalyticsFilters:
    period = (get_params.get("period") or str(DEFAULT_PERIOD_DAYS)).strip()
    city = (get_params.get("city") or "").strip()
    topic = (get_params.get("topic") or "").strip()

    raw_threshold = (get_params.get("nps_threshold") or "").strip()
    try:
        nps_threshold = float(raw_threshold.replace(",", ".")) if raw_threshold else None
    except ValueError:
        nps_threshold = None

    date_from = _parse_date(get_params.get("date_from"))
    date_to = _parse_date(get_params.get("date_to"))
    only_recommended = (get_params.get("only_recommended") or "").lower() in {"1", "true", "on", "yes"}

    return AnalyticsFilters(
        period=period,
        city=city,
        topic=topic,
        nps_threshold=nps_threshold,
        date_from=date_from,
        date_to=date_to,
        only_recommended=only_recommended,
    )


# ---------------------------------------------------------------------------
# Querysets
# ---------------------------------------------------------------------------

def feedback_queryset(filters: AnalyticsFilters) -> QuerySet[Feedback]:
    qs = Feedback.objects.select_related("speaker", "event").filter(
        created_at__gte=filters.start_dt,
        created_at__lte=filters.end_dt,
    )
    if filters.city:
        qs = qs.filter(speaker__city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(
            Q(event__topic__icontains=filters.topic)
            | Q(speaker__stack__icontains=filters.topic)
        )
    return qs


def event_queryset(filters: AnalyticsFilters) -> QuerySet[Event]:
    """Events that fall inside the filter window.

    We prefer ``event_date`` when populated, otherwise we fall back to the
    earliest related feedback's ``created_at`` so legacy imports without a
    structured date are still visible.
    """
    start = filters.start_dt
    end = filters.end_dt

    qs = Event.objects.prefetch_related("speakers").all()
    qs = qs.filter(
        Q(event_date__gte=start.date(), event_date__lte=end.date())
        | Q(event_date__isnull=True, feedbacks__created_at__gte=start, feedbacks__created_at__lte=end)
    ).distinct()

    if filters.topic:
        qs = qs.filter(Q(topic__icontains=filters.topic) | Q(speakers__stack__icontains=filters.topic)).distinct()
    if filters.city:
        qs = qs.filter(speakers__city__iexact=filters.city).distinct()
    return qs


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_nps(feedbacks: Iterable[Feedback] | QuerySet[Feedback]) -> dict[str, Any]:
    """Score breakdown for a set of feedbacks.

    Note on naming: the returned ``nps`` key is the **average score on the
    0–10 scale** (the value the dashboards display and what the ``nps_threshold``
    filter, e.g. 9.4, compares against) — *not* the classic Net Promoter Score
    percentage. Promoter/detractor counts and percentages (from which a classic
    NPS could be derived as ``promoter_pct - detractor_pct``) are returned
    alongside as separate keys.

    Accepts either a queryset (preferred, uses a single aggregate query) or any
    iterable of feedback-like objects with a ``score`` attribute.
    """
    if isinstance(feedbacks, QuerySet):
        stats = feedbacks.aggregate(
            total=Count("id"),
            promoters=Count("id", filter=Q(score__gte=PROMOTER_MIN_SCORE)),
            detractors=Count("id", filter=Q(score__lte=DETRACTOR_MAX_SCORE)),
            avg_score=Avg("score"),
        )
        total = stats["total"] or 0
        promoters = stats["promoters"] or 0
        detractors = stats["detractors"] or 0
        avg_score = stats["avg_score"]
    else:
        scores = [f.score for f in feedbacks]
        total = len(scores)
        promoters = sum(1 for s in scores if s >= PROMOTER_MIN_SCORE)
        detractors = sum(1 for s in scores if s <= DETRACTOR_MAX_SCORE)
        avg_score = (sum(scores) / total) if total else None

    passives = total - promoters - detractors
    if total == 0:
        promoter_pct = detractor_pct = passive_pct = 0.0
    else:
        promoter_pct = promoters * 100.0 / total
        detractor_pct = detractors * 100.0 / total
        passive_pct = passives * 100.0 / total

    nps = round(avg_score, 1) if avg_score is not None else 0.0

    return {
        "total": total,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "promoter_pct": round(promoter_pct, 1),
        "passive_pct": round(passive_pct, 1),
        "detractor_pct": round(detractor_pct, 1),
        "nps": nps,
        "avg_score": round(avg_score, 2) if avg_score is not None else None,
    }


def score_distribution(feedback_qs: QuerySet[Feedback]) -> dict[int, int]:
    distribution = {i: 0 for i in range(0, 11)}
    for row in feedback_qs.values("score").annotate(cnt=Count("id")):
        score = row["score"]
        if score is None:
            continue
        if 0 <= score <= 10:
            distribution[score] = row["cnt"]
    return distribution


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def city_activity(filters: AnalyticsFilters) -> list[dict[str, Any]]:
    """Section 1: Карта активности."""
    feedbacks = feedback_queryset(filters)

    rows = (
        feedbacks
        .values(city=F("speaker__city"))
        .annotate(
            feedbacks_count=Count("id"),
            speakers_count=Count("speaker_id", distinct=True),
            events_count=Count("event_id", distinct=True),
            avg_score=Avg("score"),
        )
        .order_by("-feedbacks_count")
    )

    result = []
    for row in rows:
        city = (row["city"] or "Не указан").strip() or "Не указан"
        result.append({
            "city": city,
            "feedbacks_count": row["feedbacks_count"] or 0,
            "speakers_count": row["speakers_count"] or 0,
            "events_count": row["events_count"] or 0,
            "avg_score": round(row["avg_score"], 2) if row["avg_score"] is not None else None,
        })
    return result


def speakers_ranking(filters: AnalyticsFilters, limit: int = 15) -> list[dict[str, Any]]:
    """Section 2: Рейтинг спикеров."""
    feedback_filter = Q(
        feedbacks__created_at__gte=filters.start_dt,
        feedbacks__created_at__lte=filters.end_dt,
    )
    if filters.city:
        feedback_filter &= Q(feedbacks__speaker__city__iexact=filters.city) | Q(feedbacks__isnull=True)

    qs = Speaker.objects.all()
    if filters.city:
        qs = qs.filter(city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(stack__icontains=filters.topic)
    if filters.only_recommended:
        qs = qs.filter(recommended=True)

    qs = qs.annotate(
        feedbacks_count=Count("feedbacks", filter=Q(
            feedbacks__created_at__gte=filters.start_dt,
            feedbacks__created_at__lte=filters.end_dt,
        )),
        avg_score_window=Avg("feedbacks__score", filter=Q(
            feedbacks__created_at__gte=filters.start_dt,
            feedbacks__created_at__lte=filters.end_dt,
        )),
        promoters=Count("feedbacks", filter=Q(
            feedbacks__created_at__gte=filters.start_dt,
            feedbacks__created_at__lte=filters.end_dt,
            feedbacks__score__gte=PROMOTER_MIN_SCORE,
        )),
        detractors=Count("feedbacks", filter=Q(
            feedbacks__created_at__gte=filters.start_dt,
            feedbacks__created_at__lte=filters.end_dt,
            feedbacks__score__lte=DETRACTOR_MAX_SCORE,
        )),
    ).filter(feedbacks_count__gt=0).order_by("-avg_score_window", "-feedbacks_count")

    if filters.nps_threshold is not None:
        # Порог задаётся в шкале среднего балла (0..10), см. PROJECT.txt
        qs = qs.filter(avg_score_window__gte=filters.nps_threshold)

    result = []
    for sp in qs[:limit]:
        total = sp.feedbacks_count or 0
        avg = sp.avg_score_window
        result.append({
            "id": sp.id,
            "name": sp.name,
            "sub": sp.sub,
            "city": sp.city,
            "stack": sp.stack,
            "avatar": sp.avatar_url,
            "avg_score": round(avg, 2) if avg is not None else None,
            "feedbacks_count": total,
            "nps": round(avg, 1) if avg is not None else 0.0,
            "recommended": sp.recommended,
        })
    return result


def nomination_candidates(filters: AnalyticsFilters) -> list[dict[str, Any]]:
    """Section 3: Кандидаты на выдвижение.

    Критерии по PROJECT.txt: средний балл ≥ 9.4, частота ≥ 2 выступления за
    последние 180 дней, уважаются флаги ``Speaker.recommended`` и применяются
    активные фильтры дашборда (город/тема).
    """
    now = timezone.now()
    window_start = now - timedelta(days=CANDIDATE_WINDOW_DAYS)
    threshold = filters.nps_threshold if filters.nps_threshold is not None else CANDIDATE_MIN_AVG_SCORE

    qs = Speaker.objects.all()
    if filters.city:
        qs = qs.filter(city__iexact=filters.city)
    if filters.topic:
        qs = qs.filter(stack__icontains=filters.topic)
    if filters.only_recommended:
        qs = qs.filter(recommended=True)

    qs = qs.annotate(
        feedbacks_count=Count("feedbacks", filter=Q(feedbacks__created_at__gte=window_start)),
        events_window=Count(
            "feedbacks__event",
            distinct=True,
            filter=Q(feedbacks__created_at__gte=window_start),
        ),
        avg_score_window=Avg("feedbacks__score", filter=Q(feedbacks__created_at__gte=window_start)),
        promoters=Count(
            "feedbacks",
            filter=Q(feedbacks__created_at__gte=window_start, feedbacks__score__gte=PROMOTER_MIN_SCORE),
        ),
        detractors=Count(
            "feedbacks",
            filter=Q(feedbacks__created_at__gte=window_start, feedbacks__score__lte=DETRACTOR_MAX_SCORE),
        ),
    ).filter(
        avg_score_window__gte=threshold,
        events_window__gte=CANDIDATE_MIN_EVENTS,
    ).order_by("-recommended", "-avg_score_window", "-events_window")

    result = []
    for sp in qs:
        total = sp.feedbacks_count or 0
        avg = sp.avg_score_window
        result.append({
            "id": sp.id,
            "name": sp.name,
            "sub": sp.sub,
            "city": sp.city,
            "stack": sp.stack,
            "avatar": sp.avatar_url,
            "avg_score": round(avg, 2) if avg is not None else None,
            "events_count": sp.events_window or 0,
            "feedbacks_count": total,
            "nps": round(avg, 1) if avg is not None else 0.0,
            "recommended": sp.recommended,
            "reason": _candidate_reason(sp.avg_score_window, sp.events_window, sp.recommended, threshold),
        })
    return result


def _candidate_reason(avg_score, events_window, recommended, threshold) -> str:
    parts = []
    if avg_score is not None:
        parts.append(f"средний балл {avg_score:.2f} ≥ {threshold:.2f}")
    if events_window:
        parts.append(f"{events_window} выступл. за 6 мес.")
    if recommended:
        parts.append("отметка DevRel")
    return ", ".join(parts)


def external_footprint(filters: AnalyticsFilters) -> dict[str, Any]:
    """Section 4: Внешний след."""
    qs = event_queryset(filters).filter(is_external=True)
    qs = qs.annotate(
        feedbacks_count=Count("feedbacks"),
        speakers_count=Count("speakers", distinct=True),
        avg_score=Avg("feedbacks__score"),
    ).order_by("-event_date", "-feedbacks_count")

    events = []
    for ev in qs[:25]:
        events.append({
            "id": ev.id,
            "title": ev.title,
            "location": ev.location or "—",
            "date": ev.event_date.isoformat() if ev.event_date else (ev.date or "—"),
            "link": ev.link,
            "source": ev.get_source_display() if ev.source else "—",
            "feedbacks_count": ev.feedbacks_count or 0,
            "speakers_count": ev.speakers_count or 0,
            "avg_score": round(ev.avg_score, 2) if ev.avg_score is not None else None,
        })

    summary = qs.aggregate(
        total_events=Count("id", distinct=True),
        total_speakers=Count("speakers", distinct=True),
    )

    sources = list(
        qs.values("source").annotate(cnt=Count("id", distinct=True)).order_by("-cnt")
    )
    source_labels_map = dict(Event.SOURCE_CHOICES)
    for row in sources:
        row["label"] = source_labels_map.get(row["source"], row["source"] or "—")

    return {
        "events": events,
        "total_events": summary["total_events"] or 0,
        "total_speakers": summary["total_speakers"] or 0,
        "sources": sources,
    }


def blind_zones(filters: AnalyticsFilters, cities_ref: Iterable[str] | None = None) -> dict[str, Any]:
    """Section 5: Слепые зоны.

    Берём все известные города, сравниваем их активность в окне фильтра и
    подсвечиваем те, где выступлений/отзывов мало или их нет совсем.
    """
    feedbacks = feedback_queryset(filters)

    by_city = (
        feedbacks
        .values(city=F("speaker__city"))
        .annotate(
            feedbacks_count=Count("id"),
            events_count=Count("event_id", distinct=True),
            speakers_count=Count("speaker_id", distinct=True),
        )
    )
    activity_map = {((row["city"] or "").strip() or "Не указан"): row for row in by_city}

    all_cities = set(activity_map.keys())
    if cities_ref is None:
        cities_ref = Speaker.objects.exclude(city__isnull=True).exclude(city__exact="").values_list("city", flat=True).distinct()
    for city in cities_ref:
        name = (city or "").strip() or "Не указан"
        all_cities.add(name)

    entries = []
    for city in sorted(all_cities):
        row = activity_map.get(city)
        entries.append({
            "city": city,
            "feedbacks_count": (row or {}).get("feedbacks_count", 0) or 0,
            "events_count": (row or {}).get("events_count", 0) or 0,
            "speakers_count": (row or {}).get("speakers_count", 0) or 0,
        })

    entries.sort(key=lambda r: (r["feedbacks_count"], r["events_count"]))

    silent_cities = [e for e in entries if e["feedbacks_count"] == 0][:10]
    low_cities = [e for e in entries if e["feedbacks_count"] > 0][:10]

    weak_topics = _weak_topics(filters)

    return {
        "silent_cities": silent_cities,
        "low_cities": low_cities,
        "weak_topics": weak_topics,
    }


def _weak_topics(filters: AnalyticsFilters) -> list[dict[str, Any]]:
    counts = _topic_counts(filters)
    if not counts:
        return []
    sorted_items = sorted(counts.items(), key=lambda kv: kv[1]["speakers_count"])
    return [
        {"topic": topic, **stats}
        for topic, stats in sorted_items[:6]
    ]


def _topic_counts(filters: AnalyticsFilters) -> dict[str, dict[str, Any]]:
    """Return {topic: {speakers_count, feedbacks_count, avg_score}} using Speaker.stack as CSV."""
    speakers = Speaker.objects.all()
    if filters.city:
        speakers = speakers.filter(city__iexact=filters.city)

    speaker_topics: dict[int, list[str]] = {}
    for sp in speakers.only("id", "stack"):
        topics = _split_topics(sp.stack)
        if topics:
            speaker_topics[sp.id] = topics

    if not speaker_topics:
        return {}

    feedbacks = feedback_queryset(filters).values("speaker_id", "score")
    fb_by_speaker: dict[int, list[int]] = {}
    for row in feedbacks:
        fb_by_speaker.setdefault(row["speaker_id"], []).append(row["score"])

    counts: dict[str, dict[str, Any]] = {}
    for sp_id, topics in speaker_topics.items():
        scores = fb_by_speaker.get(sp_id, [])
        for topic in topics:
            bucket = counts.setdefault(topic, {"speakers_count": 0, "feedbacks_count": 0, "_score_sum": 0, "_score_n": 0})
            bucket["speakers_count"] += 1
            bucket["feedbacks_count"] += len(scores)
            bucket["_score_sum"] += sum(scores)
            bucket["_score_n"] += len(scores)

    # finalise avg_score
    for topic, bucket in counts.items():
        bucket["avg_score"] = round(bucket["_score_sum"] / bucket["_score_n"], 2) if bucket["_score_n"] else None
        bucket.pop("_score_sum", None)
        bucket.pop("_score_n", None)
    return counts


def _split_topics(stack: str | None) -> list[str]:
    if not stack:
        return []
    if "|" in stack:
        sep = "|"
    elif ";" in stack:
        sep = ";"
    else:
        sep = ","
    parts = [p.strip() for p in stack.split(sep)]
    return [p for p in parts if len(p) >= 3 and any(ch.isalpha() for ch in p)]


def thematic_profile(filters: AnalyticsFilters) -> list[dict[str, Any]]:
    """Section 6: Тематический профиль."""
    counts = _topic_counts(filters)
    rows = [
        {"topic": topic, **stats}
        for topic, stats in counts.items()
    ]
    rows.sort(key=lambda r: r["speakers_count"], reverse=True)
    return rows[:12]


def media_library(filters: AnalyticsFilters, limit: int = 12) -> list[dict[str, Any]]:
    """Section 7: Медиатека спикеров (фото/материалы)."""
    speakers = Speaker.objects.all()
    if filters.city:
        speakers = speakers.filter(city__iexact=filters.city)
    if filters.topic:
        speakers = speakers.filter(stack__icontains=filters.topic)

    speakers = speakers.annotate(
        feedbacks_count=Count(
            "feedbacks",
            filter=Q(
                feedbacks__created_at__gte=filters.start_dt,
                feedbacks__created_at__lte=filters.end_dt,
            ),
        ),
    ).order_by("-feedbacks_count", "name")

    items = []
    for sp in speakers[:limit]:
        has_photo = bool(sp.avatar_url and not sp.avatar_url.startswith("https://i.pravatar.cc/"))
        items.append({
            "id": sp.id,
            "name": sp.name,
            "sub": sp.sub,
            "city": sp.city,
            "avatar": sp.avatar_url,
            "has_real_photo": has_photo,
            "feedbacks_count": sp.feedbacks_count or 0,
        })
    return items


# ---------------------------------------------------------------------------
# Top-level context
# ---------------------------------------------------------------------------

def build_dashboard(filters: AnalyticsFilters) -> dict[str, Any]:
    feedbacks = feedback_queryset(filters)

    nps_stats = compute_nps(feedbacks)
    distribution = score_distribution(feedbacks)

    active_cities = (
        Speaker.objects.exclude(city__isnull=True).exclude(city__exact="")
        .values_list("city", flat=True).distinct().order_by("city")
    )
    all_cities = sorted({(c or "").strip() for c in active_cities if (c or "").strip()})

    all_topics = sorted({
        t
        for stack in Speaker.objects.values_list("stack", flat=True)
        for t in _split_topics(stack)
    })

    ranking = speakers_ranking(filters)
    candidates = nomination_candidates(filters)
    external = external_footprint(filters)
    cities = city_activity(filters)
    zones = blind_zones(filters, cities_ref=all_cities)
    topics = thematic_profile(filters)

    kpis = {
        "total_feedbacks": nps_stats["total"],
        "avg_score": nps_stats["avg_score"] if nps_stats["avg_score"] is not None else 0,
        "nps": nps_stats["nps"],
        "active_speakers": feedbacks.values("speaker_id").distinct().count(),
        "active_events": feedbacks.values("event_id").distinct().count(),
        "candidates_count": len(candidates),
        "external_events": external["total_events"],
        "recommended_count": Speaker.objects.filter(recommended=True).count(),
    }

    return {
        "filters": filters.as_context(),
        "cities_list": all_cities,
        "topics_list": all_topics,
        "kpis": kpis,
        "nps_stats": nps_stats,
        "score_distribution": distribution,
        "city_activity": cities,
        "speakers_ranking": ranking,
        "candidates": candidates,
        "external_footprint": external,
        "blind_zones": zones,
        "thematic_profile": topics,
        "candidate_rules": {
            "min_avg_score": CANDIDATE_MIN_AVG_SCORE,
            "min_events": CANDIDATE_MIN_EVENTS,
            "window_days": CANDIDATE_WINDOW_DAYS,
        },
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _start_of_day(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _end_of_day(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.max.time()))

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
        "Поиск мероприятий и связей «спикер → мероприятия». "
        "Чтобы узнать, на каких мероприятиях выступает спикер, передай его ИМЯ "
        "в speaker_name (например speaker_name='Дмитрий Быков') — за ОДИН вызов "
        "вернутся все его мероприятия, включая прошедшие. Шаг через search_speakers "
        "НЕ обязателен. Без фильтра по спикеру возвращает будущие мероприятия по дате."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Подстрока темы или стека: 'ML', 'DevOps', 'Python'.",
            },
            "location": {"type": "string"},
            "is_external": {"type": "boolean"},
            "speaker_name": {
                "type": "string",
                "description": (
                    "Имя спикера (или его часть) для поиска ЕГО мероприятий. "
                    "Самый простой способ: 'Дмитрий Быков', 'Быков'. "
                    "Прошедшие мероприятия включаются автоматически."
                ),
            },
            "speaker_id": {
                "type": "integer",
                "description": (
                    "ID спикера для поиска ЕГО мероприятий, если он уже известен из "
                    "предыдущего результата. Иначе используй speaker_name."
                ),
            },
            "include_past": {
                "type": "boolean",
                "description": (
                    "Если true — включает прошедшие события. По умолчанию false, но "
                    "при поиске по конкретному спикеру (speaker_name/speaker_id) "
                    "прошедшие включаются автоматически."
                ),
            },
            "period_days": {
                "type": "integer",
                "description": "Окно будущих событий в днях. 0 — без ограничения.",
                "minimum": 0,
                "maximum": 365,
                "default": 0,
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        },
    },
)
def find_events(*, topic="", location="", is_external=None, speaker_id=None,
                speaker_name="", include_past=None, period_days=0, limit=10, _user=None):
    today = timezone.now().date()
    speaker_name = (speaker_name or "").strip()
    targeting_speaker = bool(speaker_id) or bool(speaker_name)
    # When the question is about one speaker's appearances, default to showing
    # ALL of them (past + upcoming). Weak models rarely pass include_past, so we
    # infer intent from the speaker filter instead of relying on the model.
    if include_past is None:
        include_past = targeting_speaker
    qs = Event.objects.all()
    if not include_past:
        qs = qs.filter(Q(event_date__gte=today) | Q(event_date__isnull=True, status="future"))
    if speaker_id:
        qs = qs.filter(speakers__id=speaker_id)
    if speaker_name:
        qs = qs.filter(speakers__name__icontains=speaker_name)
    if topic:
        qs = qs.filter(Q(topic__icontains=topic) | Q(speakers__stack__icontains=topic))
    if location:
        qs = qs.filter(location__icontains=location)
    if is_external is not None:
        qs = qs.filter(is_external=is_external)
    if period_days:
        qs = qs.filter(event_date__lte=today + timedelta(days=period_days))
    # When filtering by speaker, order by date DESC so recent past events show up first.
    order = ["-event_date", "-id"] if targeting_speaker and include_past else ["event_date", "id"]
    qs = qs.distinct().order_by(*order)[: max(1, min(int(limit), 10))]
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

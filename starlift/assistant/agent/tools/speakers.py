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
        "Поиск спикеров с фильтрами. Результаты ВСЕГДА отсортированы по убыванию "
        "рейтинга, поэтому для запросов «топ-N», «лучшие», «самые высокие» НЕ нужно "
        "передавать nps_min — достаточно limit. nps_min используй только когда "
        "пользователь явно назвал порог рейтинга. Для запросов «спикеры компании X», "
        "«из Сбера», «из Яндекса» — передавай название компании в параметр company."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Свободный поиск по имени, био, компании и стеку спикера. "
                    "Используй когда не понятно по какому полю искать."
                ),
            },
            "company": {
                "type": "string",
                "description": "Название компании спикера: 'Сбер', 'Яндекс', 'СберТех', 'Tinkoff'.",
            },
            "stack": {
                "type": "string",
                "description": "Технологический стек: 'Python', 'ML', 'DevOps', 'Go'.",
            },
            "city": {"type": "string"},
            "nps_min": {
                "type": "number",
                "minimum": 0,
                "maximum": 10,
                "description": (
                    "Минимальный рейтинг от 0.0 до 10.0 (средняя оценка отзывов). "
                    "НЕ указывай, если пользователь не задал порог явно."
                ),
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 10,
                "description": "Сколько спикеров вернуть. Для 'топ-10' — 10, для 'топ-3' — 3.",
            },
        },
    },
)
def search_speakers(*, query="", company="", stack="", city="", nps_min=None, limit=10, _user=None):
    qs = _scope_for(_user)
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(bio__icontains=query)
            | Q(sub__icontains=query)
            | Q(stack__icontains=query)
        )
    if company:
        qs = qs.filter(sub__icontains=company)
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
                "company": s.sub or "",
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
        "company": s.sub or "",
        "stack": s.stack or "",
        "city": s.city or "",
        "bio": bio,
        "nps": s.nps,
        "status": s.status,
    }

"""Personal, speaker-facing tools.

Unlike the search tools, these answer questions about *the logged-in speaker's
own* data: their feedback, where they can still apply, and the status of their
requests / invitations. The speaker is resolved from the server-side identity
(``_user``), never from an argument, so a speaker can only ever see themselves.

Admins/DevRel have no linked Speaker and get a clear ``not_a_speaker`` marker.
"""
from __future__ import annotations

from django.db.models import Avg, Count, Q
from django.utils import timezone

from starlift.models import EventInvitation, EventRequest, Feedback, Speaker

from . import assistant_tool

PROMOTER_MIN = 9
DETRACTOR_MAX = 6

# Hard caps so the serialized result stays under ASSISTANT_TOOL_RESULT_MAX_BYTES.
_MAX_EVENTS = 8
_MAX_COMMENTS = 8
_MAX_COMMENT_LEN = 200
_MAX_ITEMS = 8


def _my_speaker(user) -> Speaker | None:
    """The Speaker linked to the current user, or None for non-speakers."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return Speaker.objects.filter(user=user).first()


@assistant_tool(
    name="my_feedback_summary",
    description=(
        "Сводка отзывов ТЕКУЩЕГО спикера (того, кто пишет): средняя оценка, "
        "разбивка по мероприятиям и последние текстовые комментарии. Используй, "
        "когда спикер спрашивает «как мои выступления», «что обо мне пишут», "
        "«мои отзывы», «где я слабее». После получения данных кратко выдели темы "
        "из комментариев и 1–3 совета по улучшению."
    ),
    parameters={"type": "object", "properties": {}},
)
def my_feedback_summary(*, _user=None):
    speaker = _my_speaker(_user)
    if speaker is None:
        return {"error": "not_a_speaker", "hint": "Эта функция доступна только спикерам."}

    fb = Feedback.objects.filter(speaker=speaker)
    overall = fb.aggregate(
        total=Count("id"),
        avg=Avg("score"),
        promoters=Count("id", filter=Q(score__gte=PROMOTER_MIN)),
        detractors=Count("id", filter=Q(score__lte=DETRACTOR_MAX)),
    )
    total = overall["total"] or 0
    if not total:
        return {"speaker": speaker.name, "total": 0,
                "note": "Пока нет ни одного отзыва."}

    per_event = (
        fb.values("event_id", "event__title")
        .annotate(count=Count("id"), avg=Avg("score"))
        .order_by("-avg")[:_MAX_EVENTS]
    )
    recent = (
        fb.exclude(comment__isnull=True).exclude(comment__exact="")
        .order_by("-created_at")[:_MAX_COMMENTS]
    )
    return {
        "speaker": speaker.name,
        "total": total,
        "avg_score": round(overall["avg"] or 0, 2),
        "promoters": overall["promoters"] or 0,
        "detractors": overall["detractors"] or 0,
        "by_event": [
            {
                "id": r["event_id"],
                "title": r["event__title"],
                "count": r["count"],
                "avg_score": round(r["avg"] or 0, 2),
            }
            for r in per_event
        ],
        "recent_comments": [
            {"score": f.score, "comment": (f.comment or "")[:_MAX_COMMENT_LEN]}
            for f in recent
        ],
    }


@assistant_tool(
    name="find_open_events_for_me",
    description=(
        "Мероприятия, на которые ТЕКУЩИЙ спикер ещё может подать заявку сам "
        "(дедлайн подачи не прошёл) и где он пока не участвует. Используй для "
        "запросов «куда мне податься», «где я могу выступить», «открытые "
        "мероприятия для меня». Отсортировано по ближайшему дедлайну."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "Необязательный фильтр темы/стека: 'ML', 'Python'.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 10},
        },
    },
)
def find_open_events_for_me(*, topic="", limit=10, _user=None):
    speaker = _my_speaker(_user)
    if speaker is None:
        return {"error": "not_a_speaker", "hint": "Эта функция доступна только спикерам."}

    today = timezone.localdate()
    qs = (
        speaker.events.model.objects.filter(
            status="future", application_deadline__gte=today,
        )
        .exclude(speakers=speaker)               # не предлагать то, где уже участвует
        .exclude(invitations__speaker=speaker, invitations__status="pending")
    )
    topic = (topic or "").strip()
    if topic:
        qs = qs.filter(Q(topic__icontains=topic) | Q(title__icontains=topic))
    qs = qs.distinct().order_by("application_deadline", "id")[: max(1, min(int(limit), 10))]
    return {
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "topic": e.topic or "",
                "location": e.location or "",
                "date": e.event_date.isoformat() if e.event_date else (e.date or ""),
                "deadline": e.application_deadline.isoformat() if e.application_deadline else "",
            }
            for e in qs
        ]
    }


@assistant_tool(
    name="my_applications",
    description=(
        "Статус заявок и приглашений ТЕКУЩЕГО спикера: его заявки на участие/"
        "создание мероприятий (на рассмотрении / одобрено / отклонено) и "
        "приглашения от DevRel, ожидающие ответа. Используй для «что с моими "
        "заявками», «есть ли приглашения», «что мне нужно подтвердить»."
    ),
    parameters={"type": "object", "properties": {}},
)
def my_applications(*, _user=None):
    speaker = _my_speaker(_user)
    if speaker is None:
        return {"error": "not_a_speaker", "hint": "Эта функция доступна только спикерам."}

    reqs = EventRequest.objects.filter(speaker=speaker)
    counts = reqs.aggregate(
        pending=Count("id", filter=Q(status=EventRequest.STATUS_PENDING)),
        approved=Count("id", filter=Q(status=EventRequest.STATUS_APPROVED)),
        rejected=Count("id", filter=Q(status=EventRequest.STATUS_REJECTED)),
    )
    recent_reqs = reqs.order_by("-created_at")[:_MAX_ITEMS]

    pending_invites = (
        EventInvitation.objects.filter(speaker=speaker, status=EventInvitation.STATUS_PENDING)
        .select_related("event")
        .order_by("-created_at")[:_MAX_ITEMS]
    )
    return {
        "requests": {
            "pending": counts["pending"] or 0,
            "approved": counts["approved"] or 0,
            "rejected": counts["rejected"] or 0,
            "recent": [
                {
                    "kind": r.get_kind_display(),
                    "title": r.proposed_title or (r.event.title if r.event_id else r.topic) or "",
                    "status": r.get_status_display(),
                    "rejection_reason": (r.rejection_reason or "")[:_MAX_COMMENT_LEN],
                }
                for r in recent_reqs
            ],
        },
        "invitations_awaiting_response": [
            {
                "event_id": inv.event_id,
                "title": inv.event.title if inv.event_id else "",
                "message": (inv.message or "")[:_MAX_COMMENT_LEN],
            }
            for inv in pending_invites
        ],
    }

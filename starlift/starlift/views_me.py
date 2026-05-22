"""Speaker-only "/me/" sidebar pages.

Separate module so it doesn't bloat the main views.py. All views require
`@member_required`; pages other than /me/favorites/ additionally require
that the user has the `speaker` role AND a linked Speaker card.
"""

from __future__ import annotations

import csv
from collections import Counter
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.db import transaction
from django.db.models import Avg, Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import member_required

from .models import Event, EventInvitation, EventPhoto, EventRequest, Feedback, Speaker, SpeakerEventRating, SpeakerLike


def _get_speaker(user):
    return Speaker.objects.filter(user=user).first()


def speaker_required(view_func):
    """Member + role=speaker + linked Speaker. Else redirect to profile."""

    @wraps(view_func)
    @member_required
    def _wrapped(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        is_speaker = profile is not None and profile.role == "speaker"
        if not is_speaker and not request.user.is_superuser:
            return redirect("/explore/")
        speaker = _get_speaker(request.user)
        if speaker is None:
            messages.warning(
                request,
                "Ваш аккаунт ещё не привязан к карточке спикера. Обратитесь к администратору.",
            )
            return redirect("accounts:profile")
        request.my_speaker = speaker
        return view_func(request, *args, **kwargs)

    return _wrapped


def _nps_from_scores(scores):
    """NPS на шкале 0..10 (а не классической -100..+100).

    Базовая формула: ``(promoters - detractors) / total`` — диапазон -1..+1,
    где promoters ≥ 9, detractors ≤ 6. Маппим линейно в 0..10: значение
    +1 (все promoters) → 10, 0 (нейтрально) → 5, -1 (все detractors) → 0.
    """
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= 9)
    detractors = sum(1 for s in scores if s <= 6)
    raw = (promoters - detractors) / len(scores)  # -1..+1
    return round((raw + 1) * 5, 1)  # 0..10


@speaker_required
def dashboard_view(request):
    speaker = request.my_speaker
    # NPS считаем только по подтверждённым мероприятиям, чтобы спикер не мог
    # «накачать» себе статистику pending self-submissions.
    feedbacks = list(
        Feedback.objects.filter(speaker=speaker, event__verification_status=Event.VERIFICATION_VERIFIED)
        .select_related("event")
        .order_by("-created_at")
    )
    own_ratings_full = list(
        SpeakerEventRating.objects.filter(speaker=speaker, event__verification_status=Event.VERIFICATION_VERIFIED)
        .select_related("event")
        .order_by("-created_at")
    )

    # Объединённый поток баллов для NPS/распределения/тренда — отзывы зрителей
    # + собственные оценки спикера за мероприятия (учитываются равноправно).
    def _score_iter():
        for f in feedbacks:
            yield f.score, f.created_at
        for r in own_ratings_full:
            yield r.score, r.created_at

    scores = [s for s, _ in _score_iter()]
    now = timezone.now()
    last_30 = [(s, c) for s, c in _score_iter() if c >= now - timedelta(days=30)]
    last_90 = [(s, c) for s, c in _score_iter() if c >= now - timedelta(days=90)]

    distribution = Counter(scores)
    distribution_rows = [(score, distribution.get(score, 0)) for score in range(10, -1, -1)]
    max_bar = max(distribution.values()) if distribution else 1

    # Тренд по месяцам — также по объединённому потоку.
    monthly_fb = (
        Feedback.objects.filter(speaker=speaker)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"), total_score=Avg("score") * Count("id"))
    )
    monthly_sr = (
        SpeakerEventRating.objects.filter(speaker=speaker)
        .annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("id"), total_score=Avg("score") * Count("id"))
    )
    bucket: dict = {}
    for row in list(monthly_fb) + list(monthly_sr):
        m = row["month"]
        b = bucket.setdefault(m, {"month": m, "total": 0, "sum": 0.0})
        b["total"] += row["total"]
        b["sum"] += float(row["total_score"] or 0)
    monthly = sorted(
        (
            {"month": b["month"], "total": b["total"], "avg": b["sum"] / b["total"]}
            for b in bucket.values()
            if b["total"]
        ),
        key=lambda r: (r["month"] is None, r["month"]),
    )
    trend = []
    for row in monthly:
        trend.append(
            {
                "month": row["month"],
                "total": row["total"],
                "avg": round(row["avg"], 1) if row["avg"] is not None else 0,
            }
        )

    recent_comments = [f for f in feedbacks if f.comment][:5]

    # Моя средняя оценка мероприятий (только собственные оценки спикера).
    my_event_rating_avg = (
        round(sum(r.score for r in own_ratings_full) / len(own_ratings_full), 1)
        if own_ratings_full
        else None
    )
    my_event_rating_count = len(own_ratings_full)
    my_recent_event_ratings = own_ratings_full[:5]

    context = {
        "active": "dashboard",
        "speaker": speaker,
        "nps_total": _nps_from_scores(scores) if scores else None,
        "nps_30": _nps_from_scores([s for s, _ in last_30]) if last_30 else None,
        "nps_90": _nps_from_scores([s for s, _ in last_90]) if last_90 else None,
        "feedback_count": len(feedbacks) + len(own_ratings_full),
        "feedback_30": len(last_30),
        "event_count": speaker.events.count(),
        "distribution_rows": distribution_rows,
        "max_bar": max_bar,
        "trend": trend,
        "recent_comments": recent_comments,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "my_event_rating_avg": my_event_rating_avg,
        "my_event_rating_count": my_event_rating_count,
        "my_recent_event_ratings": my_recent_event_ratings,
    }
    return render(request, "me/dashboard.html", context)


@speaker_required
def feedback_view(request):
    speaker = request.my_speaker
    fb_qs = Feedback.objects.filter(speaker=speaker).select_related("event")
    sr_qs = SpeakerEventRating.objects.filter(speaker=speaker).select_related("event")

    event_id = request.GET.get("event")
    if event_id and event_id.isdigit():
        eid = int(event_id)
        fb_qs = fb_qs.filter(event_id=eid)
        sr_qs = sr_qs.filter(event_id=eid)

    score_min = request.GET.get("score_min")
    score_max = request.GET.get("score_max")
    if score_min and score_min.isdigit():
        fb_qs = fb_qs.filter(score__gte=int(score_min))
        sr_qs = sr_qs.filter(score__gte=int(score_min))
    if score_max and score_max.isdigit():
        fb_qs = fb_qs.filter(score__lte=int(score_max))
        sr_qs = sr_qs.filter(score__lte=int(score_max))

    # Маркируем источник, чтобы шаблон отрендерил «золотой» вариант.
    merged = [
        {
            "kind": "audience",
            "score": f.score,
            "comment": f.comment or "",
            "event": f.event,
            "created_at": f.created_at,
        }
        for f in fb_qs
    ] + [
        {
            "kind": "self_event",
            "score": r.score,
            "comment": r.comment or "",
            "event": r.event,
            "created_at": r.created_at,
        }
        for r in sr_qs
    ]

    sort = request.GET.get("sort", "-created_at")
    allowed_sort = {"-created_at", "created_at", "-score", "score"}
    if sort not in allowed_sort:
        sort = "-created_at"
    reverse = sort.startswith("-")
    key = sort.lstrip("-")
    merged.sort(key=lambda x: (x[key] is None, x[key]), reverse=reverse)

    feedbacks = merged

    events_for_filter = (
        speaker.events.all().order_by("-event_date").values("id", "title")
    )

    # Прошедшие мероприятия спикера + его текущая оценка (если есть),
    # чтобы прямо отсюда можно было поставить/обновить.
    past_events_qs = (
        speaker.events.filter(status="past").order_by("-event_date")
    )
    ratings_map = {
        r.event_id: r
        for r in SpeakerEventRating.objects.filter(speaker=speaker)
    }
    past_events_for_rating = []
    for ev in past_events_qs:
        r = ratings_map.get(ev.id)
        past_events_for_rating.append(
            {
                "id": ev.id,
                "title": ev.title,
                "event_date": ev.event_date,
                "date": ev.date,
                "location": ev.location,
                "my_event_rating": r.score if r else None,
                "my_event_rating_comment": r.comment if r else "",
            }
        )

    context = {
        "active": "feedback",
        "speaker": speaker,
        "feedbacks": feedbacks,
        "events_for_filter": events_for_filter,
        "past_events_for_rating": past_events_for_rating,
        "filter_event": event_id or "",
        "filter_score_min": score_min or "",
        "filter_score_max": score_max or "",
        "sort": sort,
        "total": len(feedbacks),
    }
    return render(request, "me/feedback.html", context)


@speaker_required
def events_view(request):
    speaker = request.my_speaker
    all_events = (
        speaker.events.all()
        .annotate(fb_count=Count("feedbacks", distinct=True))
        .order_by("-event_date")
    )

    my_ratings = {
        r.event_id: r
        for r in SpeakerEventRating.objects.filter(speaker=speaker)
    }

    def _serialize(ev):
        nps_value = speaker.calculate_nps(event_id=ev.id)
        rating = my_ratings.get(ev.id)
        return {
            "id": ev.id,
            "title": ev.title,
            "status": ev.status,
            "date": ev.date,
            "event_date": ev.event_date,
            "location": ev.location,
            "fb_count": getattr(ev, "fb_count", 0),
            "my_nps": nps_value if nps_value else None,
            "my_event_rating": rating.score if rating else None,
            "my_event_rating_comment": rating.comment if rating else "",
            "verification_status": ev.verification_status,
            "rejection_reason": ev.rejection_reason or "",
            "is_mine": ev.submitted_by_id == request.user.pk,
        }

    upcoming, past = [], []
    for ev in all_events:
        row = _serialize(ev)
        (past if ev.status == "past" else upcoming).append(row)

    context = {
        "active": "events",
        "speaker": speaker,
        "upcoming": upcoming,
        "past": past,
    }
    return render(request, "me/events.html", context)


@require_POST
@speaker_required
def rate_event_view(request, event_id):
    """Спикер ставит/обновляет оценку прошедшему мероприятию, в котором участвовал."""
    speaker = request.my_speaker
    event = get_object_or_404(Event, pk=event_id)

    if not event.speakers.filter(pk=speaker.pk).exists():
        return JsonResponse({"ok": False, "error": "not_participant"}, status=403)

    if event.status != "past":
        return JsonResponse({"ok": False, "error": "not_past"}, status=400)

    try:
        score = int(request.POST.get("score", "").strip())
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "bad_score"}, status=400)

    if not (0 <= score <= 10):
        return JsonResponse({"ok": False, "error": "out_of_range"}, status=400)

    comment = (request.POST.get("comment") or "").strip()[:2000]

    rating, _created = SpeakerEventRating.objects.update_or_create(
        event=event,
        speaker=speaker,
        defaults={"score": score, "comment": comment},
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "score": rating.score,
                "comment": rating.comment,
                "event_id": event.id,
            }
        )

    messages.success(request, "Оценка сохранена.")
    return redirect("me_events")


@speaker_required
def requests_view(request):
    speaker = request.my_speaker
    qs = (
        EventRequest.objects.filter(speaker=speaker)
        .select_related("event", "reviewed_by")
        .order_by("-created_at")
    )
    pending = [r for r in qs if r.status == EventRequest.STATUS_PENDING]
    approved = [r for r in qs if r.status == EventRequest.STATUS_APPROVED]
    rejected = [r for r in qs if r.status == EventRequest.STATUS_REJECTED]

    context = {
        "active": "requests",
        "speaker": speaker,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
    }
    return render(request, "me/requests.html", context)


@member_required
def favorites_view(request):
    likes = (
        SpeakerLike.objects.filter(user=request.user)
        .select_related("speaker")
        .order_by("-created_at")
    )
    speakers = []
    for like in likes:
        s = like.speaker
        speakers.append(
            {
                "id": s.id,
                "name": s.name,
                "sub": s.sub,
                "stack": s.stack,
                "city": s.city,
                "nps": s.nps,
                "avatar_url": s.avatar_url,
                "liked_at": like.created_at,
            }
        )
    context = {
        "active": "favorites",
        "speakers": speakers,
    }
    return render(request, "me/favorites.html", context)


@speaker_required
def feedback_csv_export(request):
    speaker = request.my_speaker
    feedbacks = (
        Feedback.objects.filter(speaker=speaker)
        .select_related("event")
        .order_by("-created_at")
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="my_feedback.csv"'
    response.write("﻿")  # BOM so Excel reads UTF-8

    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Дата отзыва", "Мероприятие", "Дата события", "Оценка", "Комментарий"])
    for f in feedbacks:
        writer.writerow(
            [
                f.created_at.strftime("%d.%m.%Y %H:%M"),
                f.event.title if f.event else "",
                f.event.event_date.strftime("%d.%m.%Y") if (f.event and f.event.event_date) else "",
                f.score,
                (f.comment or "").replace("\n", " ").strip(),
            ]
        )
    return response


@speaker_required
def invitations_view(request):
    speaker = request.my_speaker
    qs = (
        EventInvitation.objects.filter(speaker=speaker)
        .select_related("event", "invited_by")
        .order_by("-created_at")
    )
    pending = [inv for inv in qs if inv.status == EventInvitation.STATUS_PENDING]
    history = [inv for inv in qs if inv.status != EventInvitation.STATUS_PENDING]
    context = {
        "active": "invitations",
        "speaker": speaker,
        "pending": pending,
        "history": history,
    }
    return render(request, "me/invitations.html", context)


@require_POST
@speaker_required
def invitation_accept_view(request, invitation_id):
    from accounts.models import AuditLog
    from accounts.services import audit

    speaker = request.my_speaker
    inv = get_object_or_404(EventInvitation.objects.select_related("event"), pk=invitation_id)
    if inv.speaker_id != speaker.pk:
        return redirect("me_invitations")
    if inv.status != EventInvitation.STATUS_PENDING:
        messages.error(request, "Это приглашение уже не активно.")
        return redirect("me_invitations")
    if inv.event.status == "past":
        messages.error(request, "Событие уже прошло.")
        return redirect("me_invitations")

    with transaction.atomic():
        inv.event.speakers.add(speaker)
        inv.status = EventInvitation.STATUS_ACCEPTED
        inv.responded_at = timezone.now()
        inv.save(update_fields=["status", "responded_at"])
        audit.log(
            action=AuditLog.ACTION_EVENT_INVITATION_ACCEPTED,
            actor=request.user,
            request=request,
            target=request.user,
            metadata={"invitation_id": inv.pk, "event_id": inv.event_id},
        )
    messages.success(request, f"Вы приняли приглашение на «{inv.event.title}».")
    return redirect("me_invitations")


@require_POST
@speaker_required
def invitation_decline_view(request, invitation_id):
    from accounts.models import AuditLog
    from accounts.services import audit

    speaker = request.my_speaker
    inv = get_object_or_404(EventInvitation.objects.select_related("event"), pk=invitation_id)
    if inv.speaker_id != speaker.pk:
        return redirect("me_invitations")
    if inv.status != EventInvitation.STATUS_PENDING:
        messages.error(request, "Это приглашение уже не активно.")
        return redirect("me_invitations")

    reason = (request.POST.get("decline_reason") or "").strip()
    inv.status = EventInvitation.STATUS_DECLINED
    inv.decline_reason = reason
    inv.responded_at = timezone.now()
    inv.save(update_fields=["status", "decline_reason", "responded_at"])
    audit.log(
        action=AuditLog.ACTION_EVENT_INVITATION_DECLINED,
        actor=request.user,
        request=request,
        target=request.user,
        metadata={"invitation_id": inv.pk, "event_id": inv.event_id, "reason": reason},
    )
    messages.success(request, "Приглашение отклонено.")
    return redirect("me_invitations")


# ─────────────────────────────────────────────────────────────────────
# Загрузка прошедшего мероприятия (портфолио)
# ─────────────────────────────────────────────────────────────────────


def _humanize_ru_date(d):
    months = {1:'января',2:'февраля',3:'марта',4:'апреля',5:'мая',6:'июня',
              7:'июля',8:'августа',9:'сентября',10:'октября',11:'ноября',12:'декабря'}
    return f"{d.day} {months[d.month]} {d.year}"


@speaker_required
def event_upload_view(request, pk=None):
    """GET — форма; POST — создание/редактирование pending-события."""
    from accounts.models import AuditLog
    from accounts.services import audit
    from .forms import SpeakerEventUploadForm

    speaker = request.my_speaker
    instance = None
    if pk is not None:
        instance = get_object_or_404(Event, pk=pk)
        if instance.submitted_by_id != request.user.pk:
            return redirect("me_events")
        if instance.verification_status not in (Event.VERIFICATION_PENDING, Event.VERIFICATION_REJECTED):
            messages.info(request, "Это мероприятие уже подтверждено — изменение недоступно.")
            return redirect("me_events")

    if request.method == "POST":
        form = SpeakerEventUploadForm(request.POST, request.FILES)
        photos_files = request.FILES.getlist("photos")
        form_valid = form.is_valid()
        photo_error = None
        try:
            cleaned_photos = SpeakerEventUploadForm.validate_photos(photos_files)
        except Exception as e:
            cleaned_photos = []
            photo_error = str(e)
            form_valid = False
            if not form.errors:
                form.add_error(None, photo_error)
            else:
                form.add_error(None, photo_error)

        if form_valid:
            data = form.cleaned_data
            with transaction.atomic():
                if instance is None:
                    event = Event(
                        title=data["title"],
                        event_date=data["event_date"],
                        date=_humanize_ru_date(data["event_date"]),
                        status="past",
                        source="self",
                        verification_status=Event.VERIFICATION_PENDING,
                        submitted_by=request.user,
                    )
                else:
                    event = instance
                    event.verification_status = Event.VERIFICATION_PENDING
                    event.rejection_reason = ""
                    event.verified_by = None
                    event.verified_at = None
                    event.event_date = data["event_date"]
                    event.date = _humanize_ru_date(data["event_date"])
                    event.title = data["title"]
                    event.status = "past"

                event.location = data.get("location") or None
                event.link = data.get("link") or None
                event.topic = data.get("topic") or None
                event.description = data.get("description") or None
                event.format = data.get("format") or ""
                event.tags = data.get("tags") or ""
                event.video_url = data.get("video_url") or ""
                if data.get("presentation"):
                    event.presentation = data["presentation"]
                event.save()
                event.speakers.add(speaker)

                # Фото добавляются к существующим (не заменяют), чтобы при edit
                # пользователь мог дозагрузить. Удаление отдельных фото — TODO.
                for f in cleaned_photos:
                    EventPhoto.objects.create(event=event, image=f)

                audit.log(
                    action=AuditLog.ACTION_EVENT_SUBMISSION_SUBMITTED,
                    actor=request.user,
                    request=request,
                    target=request.user,
                    metadata={"event_id": event.pk, "edit": instance is not None},
                )
            messages.success(request, "Мероприятие отправлено на верификацию.")
            return redirect("me_events")
    else:
        initial = {}
        if instance is not None:
            initial = {
                "title": instance.title,
                "event_date": instance.event_date,
                "location": instance.location or "",
                "link": instance.link or "",
                "topic": instance.topic or "",
                "format": instance.format or "",
                "tags": instance.tags or "",
                "description": instance.description or "",
                "video_url": instance.video_url or "",
            }
        form = SpeakerEventUploadForm(initial=initial)

    return render(
        request,
        "me/event_upload.html",
        {
            "active": "events",
            "form": form,
            "instance": instance,
            "max_photos": 10,
            "today": timezone.localdate().isoformat(),
        },
    )


@require_POST
@speaker_required
def event_delete_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.submitted_by_id != request.user.pk:
        return redirect("me_events")
    if event.verification_status not in (Event.VERIFICATION_PENDING, Event.VERIFICATION_REJECTED):
        messages.error(request, "Подтверждённое мероприятие удалить нельзя.")
        return redirect("me_events")
    event.delete()
    messages.success(request, "Мероприятие удалено.")
    return redirect("me_events")

import base64
import json
import logging
import os
import re
from datetime import date
from io import BytesIO

logger = logging.getLogger(__name__)

import qrcode
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import member_required, role_required
from accounts.services.speaker_avatar import mirror_speaker_uploaded_avatar_to_profile

from . import analytics as analytics_lib
from . import home_metrics
from .forms import FeedbackForm, SpeakerForm, SpeakerSelfEditForm
from .models import Event, EventInvitation, EventRequest, Feedback, Speaker, SpeakerApplication, SpeakerEventRating, SpeakerLike

RU_MONTHS_GEN = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
RU_MONTHS_NOM = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def _month_index_ru(word: str) -> int | None:
    w = (word or "").lower()
    return RU_MONTHS_GEN.get(w) or RU_MONTHS_NOM.get(w)


def _infer_year_for_month_day(month: int, day: int, today: date) -> int:
    """If month/day without year (e.g. Highload «6 июня»): pick this year or next."""
    y = today.year
    try:
        candidate = date(y, month, day)
    except ValueError:
        return y
    if candidate >= today:
        return y
    return y + 1


def earliest_date_in_text(text: str | None, today: date) -> date | None:
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    candidates: list[date] = []

    def add(y: int, m: int, d: int) -> None:
        try:
            candidates.append(date(y, m, d))
        except ValueError:
            pass

    for mo in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", s):
        d, mth, y = int(mo.group(1)), int(mo.group(2)), int(mo.group(3))
        add(y, mth, d)

    for mo in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", s):
        y, mth, d = int(mo.group(1)), int(mo.group(2)), int(mo.group(3))
        add(y, mth, d)

    for mo in re.finditer(
        r"\b(\d{1,2})\s*[–—\-]\s*(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b",
        s,
        re.IGNORECASE,
    ):
        d1, mon_w, y = int(mo.group(1)), mo.group(3), int(mo.group(4))
        mi = _month_index_ru(mon_w)
        if mi:
            add(y, mi, d1)

    for mo in re.finditer(r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})\b", s, re.IGNORECASE):
        d, mon_w, y = int(mo.group(1)), mo.group(2), int(mo.group(3))
        mi = _month_index_ru(mon_w)
        if mi:
            add(y, mi, d)

    if not candidates:
        for mo in re.finditer(r"\b(\d{1,2})\s+([а-яё]+)\b", s, re.IGNORECASE):
            tail = s[mo.end() :]
            if re.match(r"^\s*\d{4}\b", tail):
                continue
            d, mon_w = int(mo.group(1)), mo.group(2)
            mi = _month_index_ru(mon_w)
            if not mi:
                continue
            y = _infer_year_for_month_day(mi, d, today)
            add(y, mi, d)

    if not candidates:
        for mo in re.finditer(r"\b([а-яё]+)\s+(\d{4})\b", s, re.IGNORECASE):
            mon_w, y = mo.group(1), int(mo.group(2))
            mi = _month_index_ru(mon_w)
            if mi:
                add(y, mi, 1)

    return min(candidates) if candidates else None


def effective_sort_date(event: Event, today: date) -> date | None:
    d = earliest_date_in_text(event.date, today)
    if d:
        return d
    if event.event_date:
        return event.event_date
    d = earliest_date_in_text(event.title or "", today)
    if d:
        return d
    return earliest_date_in_text((event.description or "")[:800], today)

def get_client_ip(request):
    return request.META.get('REMOTE_ADDR')

def submit_feedback_view(request, event_id, speaker_id):
    event = get_object_or_404(Event, pk=event_id)
    speaker = get_object_or_404(Speaker, pk=speaker_id)
    
    # Session handling
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key
    ip_address = get_client_ip(request)
    
    # Check if already voted
    has_voted = request.COOKIES.get(f'voted_{event.id}_{speaker.id}') == 'true' or Feedback.objects.filter(
        event=event, 
        speaker=speaker, 
        session_key=session_key
    ).exists() or Feedback.objects.filter(
        event=event, 
        speaker=speaker, 
        ip_address=ip_address
    ).exists()
    
    if has_voted:
        success_msg = request.COOKIES.get(f'voted_{event.id}_{speaker.id}') == 'true'
        return render(request, 'rate_speaker.html', {
            'event': event,
            'speaker': speaker,
            'already_voted': True,
            'success_msg': success_msg
        })

    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.event = event
            feedback.speaker = speaker
            feedback.session_key = session_key
            feedback.ip_address = ip_address

            # Rate limiting
            from datetime import timedelta
            recent_feedback = Feedback.objects.filter(ip_address=ip_address, created_at__gte=timezone.now() - timedelta(minutes=1)).exists()
            if recent_feedback:
                return render(request, 'rate_speaker.html', {
                    'event': event, 
                    'speaker': speaker, 
                    'error': 'Слишком много запросов. Подождите минуту.'
                })

            feedback.save()
            response = render(request, 'rate_speaker.html', {
                'event': event,
                'speaker': speaker,
                'already_voted': True,
                'success_msg': True
            })
            response.set_cookie(f'voted_{event.id}_{speaker.id}', 'true', max_age=60 * 60 * 24 * 365)
            return response
    else:
        form = FeedbackForm()
        
    return render(request, 'rate_speaker.html', {
        'form': form,
        'event': event,
        'speaker': speaker,
        'already_voted': False
    })

def thank_you_view(request):
    return render(request, 'thank_you.html')


@login_required
def explore_view(request):
    """Read-only landing page for guests.

    Shows only aggregate counts; nothing personally identifiable about
    individual speakers is rendered here. Members (admin/speaker) can also
    visit, but from the main nav we send them to the full dashboard instead.
    """
    from django.db.models import Count

    speakers_total = Speaker.objects.count()
    events_total = Event.objects.count()
    events_future = Event.objects.filter(status__iexact='future').count()
    events_past = Event.objects.filter(status__iexact='past').count()

    top_stacks_qs = (
        Speaker.objects.exclude(stack__isnull=True)
        .exclude(stack__exact='')
        .values('stack')
        .annotate(n=Count('id'))
        .order_by('-n')[:6]
    )
    top_cities_qs = (
        Speaker.objects.exclude(city__isnull=True)
        .exclude(city__exact='')
        .values('city')
        .annotate(n=Count('id'))
        .order_by('-n')[:6]
    )

    profile = getattr(request.user, 'profile', None)
    is_guest = bool(profile and profile.role == 'guest')

    context = {
        'speakers_total': speakers_total,
        'events_total': events_total,
        'events_future': events_future,
        'events_past': events_past,
        'top_stacks': list(top_stacks_qs),
        'top_cities': list(top_cities_qs),
        'is_guest': is_guest,
    }
    return render(request, 'explore.html', context)

@member_required
def index_view(request):
    """Home dashboard shell.

    The page is fully data-driven via ``home_api``. A compact prompt input
    sits in the hero section as a quick launcher for the floating assistant
    chat (which also renders globally via base.html).
    """
    options = home_metrics.filter_options()
    context = {
        "home_period_presets": home_metrics.ALLOWED_PERIODS,
        "home_default_period": home_metrics.DEFAULT_PERIOD_DAYS,
        "home_cities": options["cities"],
        "home_topics": options["topics"],
        "home_poll_interval_ms": 15000,
        "show_top_speakers": _is_platform_admin(request.user),
    }
    return render(request, 'index.html', context)


@member_required
@require_GET
@never_cache
def home_api(request):
    """Lightweight JSON feed for the Home dashboard.

    Returns KPIs, upcoming events, top speakers, activity feed and a short
    ``version`` hash. The frontend polls this endpoint every 15 s and skips
    re-rendering when the version hasn't changed.
    """
    filters = home_metrics.parse_filters(request.GET)
    payload = home_metrics.build_home(
        filters, include_top_speakers=_is_platform_admin(request.user)
    )
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response

def _serialize_speaker_feedbacks(speaker):
    """Объединённая лента для модалки спикера: отзывы зрителей (audience) +
    собственные оценки спикера за мероприятия (self_event), помечены
    через `kind` для отрисовки золотым в шаблоне.
    """
    items = []
    for f in speaker.feedbacks.all():
        items.append(
            {
                "kind": "audience",
                "score": f.score,
                "comment": f.comment or "",
                "date": f.created_at.strftime("%d.%m.%Y %H:%M"),
                "date_iso": f.created_at.isoformat(),
                "event_title": f.event.title if f.event else "",
            }
        )
    for r in speaker.event_ratings.all():
        items.append(
            {
                "kind": "self_event",
                "score": r.score,
                "comment": r.comment or "",
                "date": r.created_at.strftime("%d.%m.%Y %H:%M"),
                "date_iso": r.created_at.isoformat(),
                "event_title": r.event.title if r.event else "",
            }
        )
    items.sort(key=lambda x: x["date_iso"], reverse=True)
    return items


@member_required
def speakers_view(request):
    from django.db.models import Prefetch
    from accounts.models import UserProfile

    speakers = Speaker.objects.prefetch_related(
        "events",
        Prefetch("feedbacks", queryset=Feedback.objects.select_related("event").order_by("-created_at")),
        Prefetch("event_ratings", queryset=SpeakerEventRating.objects.select_related("event").order_by("-created_at")),
        Prefetch("user__profile", queryset=UserProfile.objects.only("user_id", "avatar")),
    ).all()

    speakers_data = []
    for speaker in speakers:
        feedbacks_data = _serialize_speaker_feedbacks(speaker)
        ev_list = []
        for e in speaker.events.all():
            st = (e.status or "").lower()
            if st not in ("past", "future"):
                st = "future"
            ev_list.append({"id": e.id, "t": e.title, "s": st, "d": e.date or "", "loc": (e.location or "")[:200]})

        avatar = speaker.card_avatar_url
        if speaker.user_id:
            try:
                prof = speaker.user.profile
                if prof.avatar and getattr(prof.avatar, "name", ""):
                    try:
                        avatar = prof.avatar.url
                    except ValueError:
                        pass
            except Exception:
                pass

        speakers_data.append({
            "id": speaker.id,
            "name": speaker.name,
            "sub": speaker.sub,
            "stack": speaker.stack,
            "city": speaker.city,
            "status": speaker.link_status_display,
            "nps": round(float(speaker.nps), 1) if speaker.nps else 0,
            "img": speaker.img,
            "avatar": avatar,
            "created_at": speaker.created_at.isoformat() if speaker.created_at else None,
            "events": ev_list,
            "feedbacks": feedbacks_data,
        })

    return render(request, "speakers.html", {"speakers_json": json.dumps(speakers_data)})

@member_required
def events_view(request):
    return render(request, 'events.html')

@role_required('admin', 'devrel')
def analytics_view(request):
    filters = analytics_lib.parse_filters(request.GET)
    dashboard = analytics_lib.build_dashboard(filters)

    chart_payload = {
        "score_distribution": dashboard["score_distribution"],
        "city_activity": dashboard["city_activity"][:10],
        "thematic_profile": dashboard["thematic_profile"],
        "nps_breakdown": {
            "promoters": dashboard["nps_stats"]["promoters"],
            "passives": dashboard["nps_stats"]["passives"],
            "detractors": dashboard["nps_stats"]["detractors"],
        },
    }

    context = {
        **dashboard,
        "chart_data_json": json.dumps(chart_payload, ensure_ascii=False),
    }
    return render(request, 'analytics.html', context)

@member_required
def speakers_api(request):
    try:
        from django.db.models import Count, Prefetch
        from accounts.models import UserProfile

        # Только подтверждённые мероприятия — pending/rejected self-submissions
        # не показываются в публичных списках спикеров.
        verified_events_qs = Event.objects.filter(verification_status=Event.VERIFICATION_VERIFIED)
        speakers = Speaker.objects.prefetch_related(
            Prefetch("events", queryset=verified_events_qs),
            Prefetch("feedbacks", queryset=Feedback.objects.select_related("event").order_by("-created_at")),
            Prefetch("event_ratings", queryset=SpeakerEventRating.objects.select_related("event").order_by("-created_at")),
            Prefetch("user__profile", queryset=UserProfile.objects.only("user_id", "avatar")),
        ).annotate(like_count=Count("likes", distinct=True)).all()

        liked_ids = set()
        if getattr(request.user, "is_authenticated", False):
            liked_ids = set(
                SpeakerLike.objects.filter(user=request.user).values_list("speaker_id", flat=True)
            )

        speakers_data = []
        for speaker in speakers:
            feedbacks_data = _serialize_speaker_feedbacks(speaker)

            ev_list = []
            for e in speaker.events.all():
                st = (e.status or "").lower()
                if st not in ("past", "future"):
                    st = "future"
                ev_list.append({
                    "id": e.id,
                    "t": e.title,
                    "s": st,
                    "d": e.date or "",
                    "loc": (e.location or "")[:200],
                })

            # Resolve avatar without extra DB query (profile already prefetched)
            avatar = speaker.card_avatar_url
            if speaker.user_id:
                try:
                    prof = speaker.user.profile
                    if prof.avatar and getattr(prof.avatar, "name", ""):
                        try:
                            avatar = prof.avatar.url
                        except ValueError:
                            pass
                except Exception:
                    pass

            speakers_data.append({
                "id": speaker.id,
                "name": speaker.name,
                "sub": speaker.sub,
                "stack": speaker.stack,
                "city": speaker.city,
                "status": speaker.link_status_display,
                "nps": round(float(speaker.nps), 1) if speaker.nps else 0,
                "img": speaker.img,
                "avatar": avatar,
                "created_at": speaker.created_at.isoformat() if speaker.created_at else None,
                "events": ev_list,
                "feedbacks": feedbacks_data,
                "like_count": getattr(speaker, "like_count", 0),
                "liked": speaker.id in liked_ids,
                "recommended": bool(speaker.recommended),
            })
        return JsonResponse(speakers_data, safe=False)
    except Exception:
        logger.exception("Error fetching speakers")
        return JsonResponse({"error": "Internal server error"}, status=500)

@member_required
def events_api(request):
    try:
        today = timezone.now().date()
        events = Event.objects.filter(verification_status=Event.VERIFICATION_VERIFIED).prefetch_related("speakers").all()
        # Подтягиваем оценки от спикеров одним запросом, группируем по event_id.
        ratings_by_event: dict[int, list[SpeakerEventRating]] = {}
        for r in (
            SpeakerEventRating.objects.select_related("speaker")
            .order_by("-updated_at")
        ):
            ratings_by_event.setdefault(r.event_id, []).append(r)
        events_data = []
        for event in events:
            desc = (event.description or "").strip()
            link = (event.link or "").strip()
            sched = (event.schedule or "").strip()
            is_empty_desc = not desc or desc.lower() == "none"
            is_empty_link = not link or link.lower() == "none"
            has_schedule = bool(sched) and sched.lower() != "none"
            speakers_qs = event.speakers.all()
            has_speakers = bool(speakers_qs)

            # Скрываем только полностью пустые мероприятия из автопарсинга;
            # ручные/админские/самостоятельно поданные показываем всегда.
            if event.source == 'parser' and is_empty_desc and is_empty_link and not has_speakers and not has_schedule:
                continue

            speakers_data = [
                {
                    "id": s.id,
                    "name": s.name,
                    "sub": s.sub or "",
                    "avatar": s.avatar_url,
                }
                for s in speakers_qs
            ]

            event_date_iso = event.event_date.isoformat() if event.event_date else None
            sort_d = effective_sort_date(event, today)
            sort_date_iso = sort_d.isoformat() if sort_d else None

            status_raw = (event.status or "").lower()
            is_past = status_raw == "past" or (
                sort_d is not None and sort_d < today
            )
            display_status = "past" if is_past else (event.status or "future")

            ratings = ratings_by_event.get(event.id, [])
            if ratings:
                avg_score = round(sum(r.score for r in ratings) / len(ratings), 1)
                rating_items = [
                    {
                        "speaker_id": r.speaker_id,
                        "speaker_name": r.speaker.name,
                        "speaker_avatar": r.speaker.avatar_url,
                        "score": r.score,
                        "comment": r.comment or "",
                    }
                    for r in ratings
                ]
            else:
                avg_score = None
                rating_items = []

            events_data.append(
                {
                    "id": event.id,
                    "title": event.title,
                    "status": display_status,
                    "date": event.date,
                    "event_date": event_date_iso,
                    "sort_date": sort_date_iso,
                    "location": event.location,
                    "link": event.link,
                    "description": event.description,
                    "schedule": event.schedule,
                    "speakers": speakers_data,
                    "speaker_ratings": {
                        "avg": avg_score,
                        "count": len(ratings),
                        "items": rating_items,
                    },
                    "application_deadline": event.application_deadline.isoformat() if event.application_deadline else None,
                    "can_self_submit": event.can_self_submit(),
                }
            )

        def sort_key(x: dict) -> tuple:
            is_past = x["status"] == "past"
            sd = x.get("sort_date")
            if sd:
                ord_val = date.fromisoformat(sd).toordinal()
            else:
                ord_val = 10**9 if not is_past else 0
            if is_past:
                return (1, -ord_val)
            return (0, ord_val)

        events_data.sort(key=sort_key)

        return JsonResponse(events_data, safe=False)
    except Exception:
        logger.exception("Error fetching events")
        return JsonResponse({"error": "Internal server error"}, status=500)

@role_required('admin', 'devrel')
def speaker_add(request):
    if request.method == 'POST':
        form = SpeakerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('speakers')
    else:
        form = SpeakerForm()
    return render(request, 'speaker_form.html', {'form': form, 'title': 'Добавить спикера'})

@member_required
def speaker_edit(request, pk):
    speaker = get_object_or_404(Speaker, pk=pk)
    profile = getattr(request.user, "profile", None)
    is_admin = bool(request.user.is_superuser or (profile and profile.role in ("admin", "devrel")))
    is_own_speaker = bool(profile and profile.role == "speaker" and speaker.user_id == request.user.id)

    if not is_admin and not is_own_speaker:
        return HttpResponseForbidden("Доступ запрещён")

    form_cls = SpeakerForm if is_admin else SpeakerSelfEditForm
    if request.method == 'POST':
        form = form_cls(request.POST, request.FILES, instance=speaker)
        if form.is_valid():
            updated = form.save(commit=False)
            if is_own_speaker:
                full_name = f"{request.user.first_name} {request.user.last_name}".strip()
                updated.name = full_name or request.user.username
            updated.save()
            if updated.user_id:
                mirror_speaker_uploaded_avatar_to_profile(updated)
            return redirect('speakers')
    else:
        form = form_cls(instance=speaker)
    return render(request, 'speaker_form.html', {'form': form, 'title': 'Редактировать спикера'})

@role_required('admin', 'devrel')
def speaker_delete(request, pk):
    speaker = get_object_or_404(Speaker, pk=pk)
    if request.method == 'POST':
        speaker.delete()
        return redirect('speakers')
    return render(request, 'speaker_confirm_delete.html', {'speaker': speaker})

def _is_platform_admin(user) -> bool:
    """True for admin or devrel (staff-level platform roles)."""
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role in ("admin", "devrel"))


@member_required
def qr_generator_view(request):
    """QR generator with mutually-filtering speaker ↔ event comboboxes.

    Pairs are restricted to actual M2M membership. Admin sees the full list;
    a speaker sees only their own card. Data is embedded as JSON so the
    client can autocomplete and cross-filter without extra round-trips.
    """
    linked = Speaker.objects.filter(user=request.user).first()
    is_admin = _is_platform_admin(request.user)

    if is_admin:
        speaker_qs = Speaker.objects.all().prefetch_related("events").order_by("name")
    else:
        speaker_qs = (
            Speaker.objects.filter(pk=linked.pk).prefetch_related("events")
            if linked
            else Speaker.objects.none()
        )

    speakers_payload = []
    event_index: dict[int, dict] = {}
    for sp in speaker_qs:
        sp_events = []
        for ev in sp.events.all():
            sp_events.append({"id": ev.id, "title": ev.title})
            bucket = event_index.setdefault(
                ev.id,
                {"id": ev.id, "title": ev.title, "speakers": []},
            )
            bucket["speakers"].append({"id": sp.id, "name": sp.name, "sub": sp.sub})
        sp_events.sort(key=lambda e: e["title"].lower())
        speakers_payload.append(
            {
                "id": sp.id,
                "name": sp.name,
                "sub": sp.sub,
                "events": sp_events,
            }
        )

    events_payload = sorted(event_index.values(), key=lambda e: e["title"].lower())

    return render(
        request,
        "qr_generator.html",
        {
            "is_admin": is_admin,
            "linked_speaker": linked,
            "speakers_json": json.dumps(speakers_payload, ensure_ascii=False),
            "events_json": json.dumps(events_payload, ensure_ascii=False),
            "has_data": bool(speakers_payload and events_payload),
        },
    )


def _qr_access_check(request, speaker_id, event_id):
    """Shared guard for QR display + poster download. Returns (speaker, event)
    on success, or (None, HttpResponseForbidden) on failure.
    """
    speaker = get_object_or_404(Speaker, id=speaker_id)
    event = get_object_or_404(Event, id=event_id)

    if not _is_platform_admin(request.user):
        linked = Speaker.objects.filter(user=request.user).first()
        if not linked or linked.id != speaker.id:
            return None, None, HttpResponseForbidden("Доступ запрещён")

    if not speaker.events.filter(pk=event.id).exists():
        return None, None, HttpResponseForbidden(
            f"Спикер «{speaker.name}» не участвует в мероприятии «{event.title}»."
        )
    return speaker, event, None


def _build_qr_png(url: str, box_size: int = 10, border: int = 4):
    """Return a PIL.Image of a black-on-white QR encoding ``url``."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


@member_required
def generate_qr_view(request, speaker_id, event_id):
    speaker, event, denied = _qr_access_check(request, speaker_id, event_id)
    if denied is not None:
        return denied

    rate_url = f"/rate/{event_id}/{speaker_id}/"
    full_url = request.build_absolute_uri(rate_url)
    img = _build_qr_png(full_url)

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

    context = {
        'qr_image_base64': img_str,
        'speaker': speaker,
        'event': event,
    }
    return render(request, 'qr_display.html', context)


# --- Poster download (print-ready PNG) -------------------------------------

# Fonts bundled with the repo so the poster always has Cyrillic glyphs,
# regardless of OS / container (system fonts are an unreliable fallback).
_BUNDLED_FONTS_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
_BUNDLED_FONT_REGULAR = os.path.join(_BUNDLED_FONTS_DIR, "DejaVuSans.ttf")
_BUNDLED_FONT_BOLD = os.path.join(_BUNDLED_FONTS_DIR, "DejaVuSans-Bold.ttf")

_POSTER_FONT_CANDIDATES = (
    # Windows
    r"C:\Windows\Fonts\segoeuib.ttf",  # Segoe UI Bold
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    # Debian/Ubuntu
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    # Fedora / RHEL
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    # Alpine
    "/usr/share/fonts/ttf-dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _font_supports_cyrillic(font) -> bool:
    """Probe whether the font actually carries Cyrillic glyphs.

    Pillow happily loads any TTF (and its built-in default) even when the
    glyphs requested are missing — they then render as a .notdef box (▢).
    Compare the rasterized mask of 'Я' against a PUA codepoint guaranteed
    to fall back to .notdef: if they match, the font has no Cyrillic.
    """
    try:
        cyr = bytes(font.getmask("Я"))
        pua = bytes(font.getmask("\uE000"))
        return bool(cyr) and cyr != pua
    except Exception:
        return False


def _load_font(size: int, bold_only: bool = False):
    """Best-effort TrueType loader with Cyrillic-capable fallbacks.

    Honors ``QR_POSTER_FONT_PATH`` / ``QR_POSTER_FONT_BOLD_PATH`` env vars
    for explicit overrides in deployments without standard system fonts.
    """
    from PIL import ImageFont

    env_path = os.environ.get(
        "QR_POSTER_FONT_BOLD_PATH" if bold_only else "QR_POSTER_FONT_PATH"
    )
    candidates = list(_POSTER_FONT_CANDIDATES)
    if bold_only:
        candidates = [
            p for p in candidates
            if "bd" in p.lower() or "bold" in p.lower()
        ]

    # Bundled DejaVu always carries Cyrillic — try it before system fonts so
    # the poster renders correctly even in minimal containers. An explicit env
    # override wins over everything.
    bundled = _BUNDLED_FONT_BOLD if bold_only else _BUNDLED_FONT_REGULAR
    candidates = [p for p in (env_path, bundled) if p] + candidates

    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
        if _font_supports_cyrillic(font):
            return font

    # Last resort: try Pillow's sized default (DejaVu subset on Pillow ≥ 10.1).
    # Only used when nothing else worked — its glyph set is limited but it's
    # better than the bitmap default.
    try:
        default = ImageFont.load_default(size=size)
        if _font_supports_cyrillic(default):
            return default
    except TypeError:
        pass
    return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap that respects pixel width."""
    words = (text or "").split()
    if not words:
        return [""]
    lines, current = [], words[0]
    for w in words[1:]:
        trial = current + " " + w
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


@member_required
def qr_poster_view(request, speaker_id, event_id):
    """Renders a print-ready PNG poster with brand strip, names and a big QR."""
    from PIL import Image, ImageDraw

    speaker, event, denied = _qr_access_check(request, speaker_id, event_id)
    if denied is not None:
        return denied

    rate_url = f"/rate/{event_id}/{speaker_id}/"
    full_url = request.build_absolute_uri(rate_url)
    qr_img = _build_qr_png(full_url, box_size=20, border=2)

    # Canvas — portrait, A-series-ish 1080x1500.
    W, H = 1080, 1500
    BG = (230, 240, 235)  # matches --bg-color light
    SBER = (10, 128, 59)
    DARK = (20, 44, 30)
    MUTED = (91, 117, 101)

    poster = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(poster)

    # Top brand strip
    strip_h = 90
    draw.rectangle((0, 0, W, strip_h), fill=SBER)
    brand_font = _load_font(46, bold_only=True)
    brand = "STARLIFT"
    bw = draw.textlength(brand, font=brand_font)
    draw.text(((W - bw) / 2, strip_h / 2 - 28), brand, font=brand_font, fill=(255, 255, 255))

    # Title
    title_font = _load_font(58, bold_only=True)
    title = "Оцените выступление"
    tw = draw.textlength(title, font=title_font)
    draw.text(((W - tw) / 2, strip_h + 50), title, font=title_font, fill=DARK)

    # Speaker name (wrapped)
    name_font = _load_font(72, bold_only=True)
    name_lines = _wrap_text(draw, speaker.name, name_font, W - 120)
    y = strip_h + 140
    for line in name_lines:
        lw = draw.textlength(line, font=name_font)
        draw.text(((W - lw) / 2, y), line, font=name_font, fill=SBER)
        y += 84
    if speaker.sub:
        sub_font = _load_font(34)
        sw = draw.textlength(speaker.sub, font=sub_font)
        draw.text(((W - sw) / 2, y + 6), speaker.sub, font=sub_font, fill=MUTED)
        y += 56

    # QR card
    qr_target = 640
    qr_img = qr_img.resize((qr_target, qr_target), Image.LANCZOS)
    card_pad = 30
    card_size = qr_target + card_pad * 2
    card_x = (W - card_size) // 2
    card_y = max(y + 30, H - card_size - 220)
    # White rounded card via two rectangles + corner circles (Pillow lacks rounded rect on older versions)
    try:
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_size, card_y + card_size),
            radius=28, fill=(255, 255, 255), outline=(210, 220, 215), width=2,
        )
    except AttributeError:
        draw.rectangle(
            (card_x, card_y, card_x + card_size, card_y + card_size),
            fill=(255, 255, 255), outline=(210, 220, 215), width=2,
        )
    poster.paste(qr_img, (card_x + card_pad, card_y + card_pad))

    # Footer call-to-action
    cta_font = _load_font(32)
    cta = "Наведите камеру смартфона, чтобы оставить отзыв"
    cw = draw.textlength(cta, font=cta_font)
    draw.text(((W - cw) / 2, card_y + card_size + 30), cta, font=cta_font, fill=MUTED)

    # Event pill
    pill_font = _load_font(28, bold_only=True)
    event_text = event.title
    et_w = draw.textlength(event_text, font=pill_font)
    pill_pad_x, pill_pad_y = 28, 14
    pill_w = et_w + pill_pad_x * 2
    pill_h = 28 + pill_pad_y * 2
    pill_x = (W - pill_w) / 2
    pill_y = card_y + card_size + 90
    try:
        draw.rounded_rectangle(
            (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
            radius=pill_h / 2, fill=SBER,
        )
    except AttributeError:
        draw.rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), fill=SBER)
    draw.text((pill_x + pill_pad_x, pill_y + pill_pad_y - 4), event_text, font=pill_font, fill=(255, 255, 255))

    # Serialize
    out = BytesIO()
    poster.save(out, format="PNG", optimize=True)
    out.seek(0)

    from django.http import HttpResponse

    import re as _re

    def _slug(s: str) -> str:
        s = _re.sub(r"[^\w\-]+", "_", s, flags=_re.UNICODE).strip("_")
        return s[:60] or "qr"

    filename = f"qr_{_slug(speaker.name)}_{_slug(event.title)}.png"
    response = HttpResponse(out.getvalue(), content_type="image/png")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _get_speaker_for_user(user):
    """Returns Speaker linked to user, or None."""
    return Speaker.objects.filter(user=user).first()


@member_required
def submit_event_request_view(request):
    """Спикер подаёт заявку на создание нового мероприятия."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    speaker = _get_speaker_for_user(request.user)
    if not speaker:
        return JsonResponse({'error': 'no_speaker_profile'}, status=403)

    title = (request.POST.get('proposed_title') or '').strip()
    if not title:
        return JsonResponse({'error': 'title_required'}, status=400)

    raw_date = (request.POST.get('proposed_event_date') or '').strip()
    parsed_date = None
    if raw_date:
        try:
            from datetime import datetime
            parsed_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'error': 'bad_date'}, status=400)

    req = EventRequest.objects.create(
        kind=EventRequest.KIND_CREATE,
        speaker=speaker,
        proposed_title=title,
        proposed_description=(request.POST.get('proposed_description') or '').strip(),
        proposed_event_date=parsed_date,
        proposed_location=(request.POST.get('proposed_location') or '').strip(),
        proposed_link=(request.POST.get('proposed_link') or '').strip(),
        topic=(request.POST.get('topic') or '').strip(),
        comment=(request.POST.get('comment') or '').strip(),
    )
    return JsonResponse({'ok': True, 'id': req.id})


@member_required
def submit_join_request_view(request, event_id):
    """Спикер подаёт заявку на участие в существующем мероприятии."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    speaker = _get_speaker_for_user(request.user)
    if not speaker:
        return JsonResponse({'error': 'no_speaker_profile'}, status=403)

    event = get_object_or_404(Event, pk=event_id)

    if event.speakers.filter(pk=speaker.pk).exists():
        return JsonResponse({'error': 'already_participant'}, status=400)

    if EventRequest.objects.filter(
        kind=EventRequest.KIND_JOIN,
        speaker=speaker, event=event,
        status=EventRequest.STATUS_PENDING,
    ).exists():
        return JsonResponse({'error': 'already_pending'}, status=400)

    if not event.can_self_submit():
        return JsonResponse({'error': 'submissions_closed'}, status=400)

    topic = (request.POST.get('topic') or '').strip()
    if not topic:
        return JsonResponse({'error': 'topic_required'}, status=400)

    req = EventRequest.objects.create(
        kind=EventRequest.KIND_JOIN,
        speaker=speaker,
        event=event,
        topic=topic,
        comment=(request.POST.get('comment') or '').strip(),
    )
    return JsonResponse({'ok': True, 'id': req.id})


_RU_MONTHS_GEN_BY_NUM = {
    1: 'января', 2: 'февраля', 3: 'марта', 4: 'апреля', 5: 'мая', 6: 'июня',
    7: 'июля', 8: 'августа', 9: 'сентября', 10: 'октября', 11: 'ноября', 12: 'декабря',
}


def _parse_event_post(request):
    """Parse common Event fields from POST. Returns dict, raises ValueError on bad data."""
    from datetime import datetime
    title = (request.POST.get('title') or '').strip()
    if not title:
        raise ValueError('title_required')
    raw_date = (request.POST.get('event_date') or '').strip()
    parsed_date = None
    human_date = None
    if raw_date:
        try:
            parsed_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
            human_date = f"{parsed_date.day} {_RU_MONTHS_GEN_BY_NUM[parsed_date.month]} {parsed_date.year}"
        except (ValueError, KeyError):
            raise ValueError('bad_date')
    raw_deadline = (request.POST.get('application_deadline') or '').strip()
    parsed_deadline = None
    if raw_deadline:
        try:
            parsed_deadline = datetime.strptime(raw_deadline, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('bad_deadline')
    return {
        'title': title,
        'description': (request.POST.get('description') or '').strip() or None,
        'event_date': parsed_date,
        'date': human_date,
        'location': (request.POST.get('location') or '').strip() or None,
        'link': (request.POST.get('link') or '').strip() or None,
        'topic': (request.POST.get('topic') or '').strip() or None,
        'schedule': (request.POST.get('schedule') or '').strip() or None,
        'application_deadline': parsed_deadline,
    }


@role_required('admin', 'devrel')
def admin_event_create(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    try:
        data = _parse_event_post(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    today = timezone.now().date()
    status = 'past' if (data['event_date'] and data['event_date'] < today) else 'future'
    ev = Event.objects.create(source='internal', status=status, **data)
    speaker_ids = request.POST.getlist('speaker_ids')
    if speaker_ids:
        ev.speakers.set(Speaker.objects.filter(pk__in=speaker_ids))
    return JsonResponse({'ok': True, 'id': ev.id})


@role_required('admin', 'devrel')
def admin_event_edit(request, event_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    ev = get_object_or_404(Event, pk=event_id)
    try:
        data = _parse_event_post(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    today = timezone.now().date()
    for f, v in data.items():
        setattr(ev, f, v)
    if data['event_date']:
        ev.status = 'past' if data['event_date'] < today else 'future'
    ev.save()
    speaker_ids = request.POST.getlist('speaker_ids')
    if speaker_ids:
        ev.speakers.set(Speaker.objects.filter(pk__in=speaker_ids))
    return JsonResponse({'ok': True, 'id': ev.id})


@role_required('admin', 'devrel')
def admin_event_remove_speaker(request, event_id, speaker_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    ev = get_object_or_404(Event, pk=event_id)
    sp = get_object_or_404(Speaker, pk=speaker_id)
    ev.speakers.remove(sp)
    return JsonResponse({'ok': True})


@role_required('admin', 'devrel')
def admin_event_delete(request, event_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    ev = get_object_or_404(Event, pk=event_id)
    ev.delete()
    return JsonResponse({'ok': True})


@role_required('admin', 'devrel')
def admin_pending_requests_api(request):
    """Список pending заявок для уведомлений админа."""
    qs = EventRequest.objects.filter(
        status=EventRequest.STATUS_PENDING
    ).select_related('speaker', 'event').order_by('-created_at')[:30]
    items = []
    for r in qs:
        items.append({
            'id': r.id,
            'kind': r.kind,
            'speaker_name': r.speaker.name,
            'event_title': r.event.title if r.event else r.proposed_title,
            'topic': r.topic,
            'created_at': r.created_at.isoformat(),
        })
    total = EventRequest.objects.filter(status=EventRequest.STATUS_PENDING).count()
    return JsonResponse({'count': total, 'requests': items})


@role_required('admin', 'devrel')
def speaker_recommend_toggle(request, speaker_id):
    """Admin-only: toggle Speaker.recommended flag."""
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    speaker = get_object_or_404(Speaker, pk=speaker_id)
    speaker.recommended = not speaker.recommended
    speaker.save(update_fields=["recommended"])
    return JsonResponse({"recommended": speaker.recommended})


@member_required
def speaker_like_toggle(request, speaker_id):
    """Toggle like for the current authenticated member on a speaker."""
    if request.method != "POST":
        return JsonResponse({"error": "method_not_allowed"}, status=405)
    speaker = get_object_or_404(Speaker, pk=speaker_id)
    qs = SpeakerLike.objects.filter(user=request.user, speaker=speaker)
    if qs.exists():
        qs.delete()
        liked = False
    else:
        SpeakerLike.objects.create(user=request.user, speaker=speaker)
        liked = True
    like_count = SpeakerLike.objects.filter(speaker=speaker).count()
    return JsonResponse({"liked": liked, "like_count": like_count})


@member_required
def notifications_api(request):
    """Aggregated bell payload: event-requests (admin/devrel) + support tickets.

    Speakers/devrel see only their own support; admin/devrel additionally see
    pending event-requests. Guests cannot reach this view.
    """
    from support.services import notifications as support_notif

    user = request.user
    profile = getattr(user, 'profile', None)
    is_admin = user.is_superuser or (profile and profile.role in ('admin', 'devrel'))

    event_items = []
    event_count = 0
    application_items = []
    application_count = 0
    speaker_event_items = []
    speaker_event_count = 0
    if is_admin:
        qs = EventRequest.objects.filter(
            status=EventRequest.STATUS_PENDING
        ).select_related('speaker', 'event').order_by('-created_at')[:10]
        for r in qs:
            event_items.append({
                'id': r.id,
                'kind': r.kind,
                'speaker_name': r.speaker.name,
                'event_title': r.event.title if r.event else r.proposed_title,
                'topic': r.topic,
                'created_at': r.created_at.isoformat(),
            })
        event_count = EventRequest.objects.filter(status=EventRequest.STATUS_PENDING).count()

        from accounts.views.console import _devrel_visible_applications
        app_qs = (
            _devrel_visible_applications(user)
            .filter(status=SpeakerApplication.STATUS_PENDING)
            .select_related('applicant')[:10]
        )
        for a in app_qs:
            name = (f"{a.applicant.first_name} {a.applicant.last_name}".strip() or a.applicant.username)
            application_items.append({
                'id': a.id,
                'applicant_name': name,
                'company': a.company,
                'city': a.city,
                'created_at': a.created_at.isoformat(),
                'url': f'/console/speaker-applications/{a.id}/',
            })
        application_count = _devrel_visible_applications(user).filter(
            status=SpeakerApplication.STATUS_PENDING
        ).count()

        from accounts.views.console import _devrel_visible_speaker_events
        se_qs = _devrel_visible_speaker_events(user)[:10]
        for ev in se_qs:
            submitter = ev.submitted_by
            submitter_name = ''
            company = ''
            if submitter is not None:
                submitter_name = (f"{submitter.first_name} {submitter.last_name}".strip()) or submitter.username
                try:
                    company = (submitter.profile.company or '')
                except Exception:
                    company = ''
            speaker_event_items.append({
                'id': ev.id,
                'title': ev.title,
                'submitter_name': submitter_name,
                'company': company,
                'created_at': ev.created_at.isoformat() if ev.created_at else None,
                'url': f'/console/speaker-events/{ev.id}/',
            })
        speaker_event_count = _devrel_visible_speaker_events(user).count()

    support_tickets = list(support_notif.unread_tickets(user)[:10])
    support_items = []
    for t in support_tickets:
        support_items.append({
            'id': t.id,
            'subject': t.subject,
            'author': t.author_label,
            'last_message_at': t.last_message_at.isoformat() if t.last_message_at else None,
            'url': f'/assistant/support/t/{t.id}/',
        })
    support_count = support_notif.unread_count(user)

    invitation_items = []
    invitation_count = 0
    if profile and profile.role == 'speaker':
        speaker = Speaker.objects.filter(user=user).first()
        if speaker:
            inv_qs = (
                EventInvitation.objects.filter(speaker=speaker, status=EventInvitation.STATUS_PENDING)
                .select_related("event", "invited_by")
                .order_by("-created_at")[:10]
            )
            for inv in inv_qs:
                invited_by_name = inv.invited_by.get_full_name() if inv.invited_by else "DevRel"
                invitation_items.append({
                    'id': inv.id,
                    'event_title': inv.event.title,
                    'event_date': inv.event.event_date.isoformat() if inv.event.event_date else (inv.event.date or ''),
                    'invited_by_name': invited_by_name or (inv.invited_by.username if inv.invited_by else "DevRel"),
                    'created_at': inv.created_at.isoformat(),
                    'url': '/me/invitations/',
                })
            invitation_count = EventInvitation.objects.filter(
                speaker=speaker, status=EventInvitation.STATUS_PENDING,
            ).count()

    return JsonResponse({
        'total': event_count + support_count + application_count + invitation_count + speaker_event_count,
        'event_requests': {'count': event_count, 'items': event_items},
        'speaker_applications': {'count': application_count, 'items': application_items},
        'speaker_events': {'count': speaker_event_count, 'items': speaker_event_items},
        'support': {'count': support_count, 'items': support_items},
        'event_invitations': {'count': invitation_count, 'items': invitation_items},
    })


@role_required('admin', 'devrel')
def admin_quick_approve(request, request_id):
    """Быстрое одобрение из колокольчика."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    from django.db import transaction as _tx
    req = get_object_or_404(EventRequest, pk=request_id)
    if req.status != EventRequest.STATUS_PENDING:
        return JsonResponse({'error': 'already_processed'}, status=400)
    with _tx.atomic():
        if req.kind == EventRequest.KIND_CREATE:
            today = timezone.now().date()
            pd = req.proposed_event_date
            human_date = f"{pd.day} {_RU_MONTHS_GEN_BY_NUM[pd.month]} {pd.year}" if pd else None
            ev = Event.objects.create(
                title=req.proposed_title,
                description=req.proposed_description or None,
                event_date=pd,
                date=human_date,
                location=req.proposed_location or None,
                link=req.proposed_link or None,
                source='self',
                status='past' if (pd and pd < today) else 'future',
            )
            ev.speakers.add(req.speaker)
            req.event = ev
        elif req.kind == EventRequest.KIND_JOIN and req.event:
            req.event.speakers.add(req.speaker)
        req.status = EventRequest.STATUS_APPROVED
        req.reviewed_at = timezone.now()
        req.reviewed_by = request.user
        req.save()
    return JsonResponse({'ok': True})


@member_required
def my_event_requests_api(request):
    """Список заявок текущего спикера."""
    speaker = _get_speaker_for_user(request.user)
    if not speaker:
        return JsonResponse({'requests': []})

    requests_qs = EventRequest.objects.filter(speaker=speaker).select_related('event')
    items = []
    for r in requests_qs:
        items.append({
            'id': r.id,
            'kind': r.kind,
            'kind_label': r.get_kind_display(),
            'status': r.status,
            'status_label': r.get_status_display(),
            'topic': r.topic,
            'comment': r.comment,
            'event': {'id': r.event.id, 'title': r.event.title} if r.event else None,
            'proposed_title': r.proposed_title,
            'proposed_description': r.proposed_description,
            'proposed_event_date': r.proposed_event_date.isoformat() if r.proposed_event_date else None,
            'proposed_location': r.proposed_location,
            'proposed_link': r.proposed_link,
            'rejection_reason': r.rejection_reason,
            'created_at': r.created_at.isoformat(),
        })
    return JsonResponse({'requests': items})

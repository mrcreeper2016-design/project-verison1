import base64
import json
import logging
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
from .models import Event, EventRequest, Feedback, Speaker

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
    payload = home_metrics.build_home(filters)
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response

@member_required
def speakers_view(request):
    from django.db.models import Prefetch
    from accounts.models import UserProfile

    speakers = Speaker.objects.prefetch_related(
        "events",
        Prefetch("feedbacks", queryset=Feedback.objects.select_related("event").order_by("-created_at")),
        Prefetch("user__profile", queryset=UserProfile.objects.only("user_id", "avatar")),
    ).all()

    speakers_data = []
    for speaker in speakers:
        feedbacks_data = [
            {
                "score": f.score,
                "comment": f.comment,
                "date": f.created_at.strftime("%d.%m.%Y %H:%M"),
                "event_title": f.event.title,
            }
            for f in speaker.feedbacks.all()
        ]
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
            "events": ev_list,
            "feedbacks": feedbacks_data,
        })

    return render(request, "speakers.html", {"speakers_json": json.dumps(speakers_data)})

@member_required
def events_view(request):
    return render(request, 'events.html')

@role_required('admin')
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
        from django.db.models import Prefetch
        from accounts.models import UserProfile

        speakers = Speaker.objects.prefetch_related(
            "events",
            Prefetch("feedbacks", queryset=Feedback.objects.select_related("event").order_by("-created_at")),
            Prefetch("user__profile", queryset=UserProfile.objects.only("user_id", "avatar")),
        ).all()

        speakers_data = []
        for speaker in speakers:
            feedbacks_data = [
                {
                    "score": f.score,
                    "comment": f.comment,
                    "date": f.created_at.strftime("%d.%m.%Y %H:%M"),
                    "event_title": f.event.title,
                }
                for f in speaker.feedbacks.all()
            ]

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
                "events": ev_list,
                "feedbacks": feedbacks_data
            })
        return JsonResponse(speakers_data, safe=False)
    except Exception:
        logger.exception("Error fetching speakers")
        return JsonResponse({"error": "Internal server error"}, status=500)

@member_required
def events_api(request):
    try:
        today = timezone.now().date()
        events = Event.objects.prefetch_related("speakers").all()
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

@role_required('admin')
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
    is_admin = bool(request.user.is_superuser or (profile and profile.role == "admin"))
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

@role_required('admin')
def speaker_delete(request, pk):
    speaker = get_object_or_404(Speaker, pk=pk)
    if request.method == 'POST':
        speaker.delete()
        return redirect('speakers')
    return render(request, 'speaker_confirm_delete.html', {'speaker': speaker})

def _is_platform_admin(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


@member_required
def qr_generator_view(request):
    linked = Speaker.objects.filter(user=request.user).first()
    if _is_platform_admin(request.user):
        speakers = Speaker.objects.all().order_by("name")
        events = Event.objects.all().order_by("title")
        qr_self_only = False
        qr_speaker_id = None
    else:
        speakers = []
        qr_self_only = True
        qr_speaker_id = linked.id if linked else None
        events = (
            linked.events.all().order_by("title")
            if linked
            else Event.objects.none()
        )
    return render(
        request,
        "qr_generator.html",
        {
            "speakers": speakers,
            "events": events,
            "qr_self_only": qr_self_only,
            "qr_speaker_id": qr_speaker_id,
            "linked_speaker": linked,
        },
    )


@member_required
def generate_qr_view(request, speaker_id, event_id):
    speaker = get_object_or_404(Speaker, id=speaker_id)
    event = get_object_or_404(Event, id=event_id)

    if not _is_platform_admin(request.user):
        linked = Speaker.objects.filter(user=request.user).first()
        if not linked or linked.id != speaker.id:
            return HttpResponseForbidden("Доступ запрещён")
        if not speaker.events.filter(pk=event.id).exists():
            return HttpResponseForbidden("Доступ запрещён")

    # Формируем URL для страницы оценки
    rate_url = f"/rate/{event_id}/{speaker_id}/"
    full_url = request.build_absolute_uri(rate_url)

    # Генерируем QR-код
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(full_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Сохраняем в base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

    context = {
        'qr_image_base64': img_str,
        'speaker': speaker,
        'event': event,
    }
    return render(request, 'qr_display.html', context)


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
    return {
        'title': title,
        'description': (request.POST.get('description') or '').strip() or None,
        'event_date': parsed_date,
        'date': human_date,
        'location': (request.POST.get('location') or '').strip() or None,
        'link': (request.POST.get('link') or '').strip() or None,
        'topic': (request.POST.get('topic') or '').strip() or None,
        'schedule': (request.POST.get('schedule') or '').strip() or None,
    }


@role_required('admin')
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


@role_required('admin')
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


@role_required('admin')
def admin_event_remove_speaker(request, event_id, speaker_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    ev = get_object_or_404(Event, pk=event_id)
    sp = get_object_or_404(Speaker, pk=speaker_id)
    ev.speakers.remove(sp)
    return JsonResponse({'ok': True})


@role_required('admin')
def admin_event_delete(request, event_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    ev = get_object_or_404(Event, pk=event_id)
    ev.delete()
    return JsonResponse({'ok': True})


@role_required('admin')
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


@role_required('admin')
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

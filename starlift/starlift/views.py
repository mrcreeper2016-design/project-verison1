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
from .models import Event, Feedback, Speaker

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

    The page is fully data-driven via ``home_api``; we only hand the template
    initial filter options so the dropdowns are usable before the first poll
    finishes.
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
    return render(request, "speakers.html")

@member_required
def events_view(request):
    return render(request, 'events.html')

@member_required
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
        speakers = Speaker.objects.prefetch_related("events").all()
        speakers_data = []
        for speaker in speakers:
            # Получаем отзывы
            feedbacks_qs = speaker.feedbacks.all().order_by('-created_at')
            feedbacks_data = []
            for f in feedbacks_qs:
                feedbacks_data.append({
                    "score": f.score,
                    "comment": f.comment,
                    "date": f.created_at.strftime("%d.%m.%Y %H:%M"),
                    "event_title": f.event.title
                })

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

            speakers_data.append({
                "id": speaker.id,
                "name": speaker.name,
                "sub": speaker.sub,
                "stack": speaker.stack,
                "city": speaker.city,
                "status": speaker.link_status_display,
                "nps": int(speaker.nps) if speaker.nps else 0,
                "img": speaker.img,
                "avatar": speaker.avatar_url,
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

            if is_empty_desc and is_empty_link and not has_speakers and not has_schedule:
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

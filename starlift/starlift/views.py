import base64
import json
from io import BytesIO

import qrcode
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from accounts.decorators import member_required, role_required

from . import analytics as analytics_lib
from . import home_metrics
from .forms import FeedbackForm, SpeakerForm, SpeakerSelfEditForm
from .models import Event, Feedback, Speaker

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
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
            from django.utils import timezone
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
            response.set_cookie(f'voted_{event.id}_{speaker.id}', 'true', max_age=315360000)
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
    editable_speaker_id = None
    profile = getattr(request.user, "profile", None)
    if profile and profile.role == "speaker":
        editable_speaker_id = (
            Speaker.objects.filter(user=request.user).values_list("id", flat=True).first()
        )
    return render(
        request,
        'speakers.html',
        {"editable_speaker_id": editable_speaker_id},
    )

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
        speakers = Speaker.objects.all()
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
            
            speakers_data.append({
                "id": speaker.id,
                "name": speaker.name,
                "sub": speaker.sub,
                "stack": speaker.stack,
                "city": speaker.city,
                "status": speaker.status,
                "nps": int(speaker.nps) if speaker.nps else 0,
                "img": speaker.img,
                "avatar": speaker.avatar_url,
                "events": [{"t": e.title, "s": e.status} for e in speaker.events.all()],
                "feedbacks": feedbacks_data
            })
        return JsonResponse(speakers_data, safe=False)
    except Exception as e:
        print(f"Error fetching speakers: {e}")
        return JsonResponse([], safe=False)

@member_required
def events_api(request):
    try:
        events = Event.objects.all()
        events_data = []
        for event in events:
            # Check if there is some useful info
            is_empty_desc = not event.description or event.description.lower() == 'none' or event.description.strip() == ''
            is_empty_link = not event.link or event.link.lower() == 'none' or event.link.strip() == ''
            
            if is_empty_desc and is_empty_link:
                continue
                
            events_data.append({
                "id": event.id,
                "title": event.title,
                "status": event.status,
                "date": event.date,
                "location": event.location,
                "link": event.link,
                "description": event.description,
                "schedule": event.schedule
            })
            
        # Sort so that 'past' events are at the bottom
        events_data.sort(key=lambda x: (1 if x['status'] == 'past' else 0, x['date'] if x['date'] else ''))
        
        return JsonResponse(events_data, safe=False)
    except Exception as e:
        print(f"Error fetching events: {e}")
        return JsonResponse([], safe=False)

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

@member_required
def qr_generator_view(request):
    speakers = Speaker.objects.all()
    events = Event.objects.all()
    return render(request, 'qr_generator.html', {'speakers': speakers, 'events': events})

@member_required
def generate_qr_view(request, speaker_id, event_id):
    speaker = get_object_or_404(Speaker, id=speaker_id)
    event = get_object_or_404(Event, id=event_id)

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

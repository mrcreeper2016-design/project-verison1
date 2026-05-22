"""Self-service flow: guest fills speaker profile → SpeakerApplication created.

DevRel moderates via the existing `/console/event-requests/` page.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from starlift.models import SpeakerApplication

from ..forms import SpeakerApplicationForm
from ..models import AuditLog, UserProfile
from ..services import audit
from ..services.companies import ALLOWED_COMPANIES


def _ensure_guest(view_func):
    """Allow only guests (non-promoted users) to reach the application screens."""
    from functools import wraps

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        if profile is None or profile.role != UserProfile.ROLE_GUEST:
            return redirect("/")
        return view_func(request, *args, **kwargs)

    return _wrapped


@_ensure_guest
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def speaker_application_form_view(request: HttpRequest) -> HttpResponse:
    profile = request.user.profile
    existing = SpeakerApplication.objects.filter(applicant=request.user).first()

    if request.method == "GET" and existing and existing.status == SpeakerApplication.STATUS_PENDING:
        return redirect(reverse("accounts:speaker_application_pending"))

    initial = {}
    if existing:
        initial = {
            "company": existing.company,
            "city": existing.city,
            "stack": existing.stack,
            "description": existing.description,
        }
    elif profile.company:
        initial["company"] = profile.company

    if request.method == "POST":
        form = SpeakerApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            app = existing or SpeakerApplication(applicant=request.user)
            app.company = data["company"]
            app.city = data["city"]
            app.stack = data["stack"]
            app.description = data["description"]
            app.status = SpeakerApplication.STATUS_PENDING
            app.submitted_at = timezone.now()
            app.rejection_reason = ""
            app.reviewed_at = None
            app.reviewed_by = None
            app.save()

            profile.company = data["company"]
            profile.bio = data["description"]
            update_fields = ["company", "bio", "updated_at"]
            avatar = data.get("avatar")
            if avatar:
                profile.avatar = avatar
                update_fields.append("avatar")
            profile.save(update_fields=update_fields)

            audit.log(
                action=AuditLog.ACTION_SPEAKER_APPLICATION_SUBMITTED,
                actor=request.user,
                request=request,
                target=app,
                metadata={"company": app.company, "city": app.city},
            )
            messages.success(request, "Заявка отправлена. DevRel рассмотрит её в ближайшее время.")
            return redirect(reverse("accounts:speaker_application_pending"))
    else:
        form = SpeakerApplicationForm(initial=initial)

    return render(
        request,
        "accounts/speaker_application_form.html",
        {
            "form": form,
            "existing": existing,
            "is_resubmit": bool(existing and existing.status == SpeakerApplication.STATUS_REJECTED),
            "allowed_companies": ALLOWED_COMPANIES,
        },
    )


@_ensure_guest
@never_cache
@require_http_methods(["GET"])
def application_pending_view(request: HttpRequest) -> HttpResponse:
    app = SpeakerApplication.objects.filter(applicant=request.user).first()
    if app is None:
        return redirect(reverse("accounts:speaker_application_form"))
    if app.status == SpeakerApplication.STATUS_REJECTED:
        return redirect(reverse("accounts:speaker_application_form"))
    return render(
        request,
        "accounts/speaker_application_pending.html",
        {"application": app},
    )

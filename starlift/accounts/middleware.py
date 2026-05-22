"""Middleware that nudges guest users toward the speaker-application flow.

A guest who has verified their email but has not yet submitted (or has
pending) a SpeakerApplication is redirected to the form / pending page when
they try to reach any member-level URL. The whitelist below is the only set
of routes a guest may freely browse.
"""
from __future__ import annotations

from django.shortcuts import redirect
from django.urls import reverse


_WHITELIST_PREFIXES = (
    "/auth/",
    "/application/",
    "/profile/",
    "/explore/",
    "/static/",
    "/media/",
    "/admin/",
    "/favicon",
)


class GuestApplicationRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return self.get_response(request)

        profile = getattr(user, "profile", None)
        if profile is None or profile.role != "guest":
            return self.get_response(request)

        path = request.path
        for prefix in _WHITELIST_PREFIXES:
            if path.startswith(prefix):
                return self.get_response(request)

        # Defer the import: SpeakerApplication lives in another app and is
        # not loaded at module-import time on every settings refresh.
        from starlift.models import SpeakerApplication

        app = SpeakerApplication.objects.filter(applicant=user).first()
        if app is None or app.status == SpeakerApplication.STATUS_REJECTED:
            return redirect(reverse("accounts:speaker_application_form"))
        if app.status == SpeakerApplication.STATUS_PENDING:
            return redirect(reverse("accounts:speaker_application_pending"))

        return self.get_response(request)

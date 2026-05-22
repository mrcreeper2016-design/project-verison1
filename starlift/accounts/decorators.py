"""Role-based view decorators.

Read the role from `request.user.profile.role`. If a user somehow has no
profile (shouldn't happen after backfill + signals), we treat them as
insufficient-role.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


def _has_role(user, roles: set[str]) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if profile is None:
        return False
    return profile.role in roles


def role_required(*roles):
    allowed = set(roles)

    def decorator(view_func):
        @wraps(view_func)
        @login_required(login_url=settings.LOGIN_URL)
        def _wrapped(request, *args, **kwargs):
            if not _has_role(request.user, allowed):
                return HttpResponseForbidden("Доступ запрещён")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def anonymous_required(redirect_to: str = "/"):
    """Bounce already-logged-in users away from login / reset pages."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.is_authenticated:
                return redirect(redirect_to)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def member_required(view_func):
    """Require any non-guest role (`admin`, `devrel`, `speaker`).

    Unlike ``role_required``, guests are *redirected* to the explore page
    instead of getting a 403 — this is our main pattern for "authenticated
    but not yet approved" users who land on member-only URLs by mistake.
    """

    @wraps(view_func)
    @login_required(login_url=settings.LOGIN_URL)
    def _wrapped(request, *args, **kwargs):
        if _has_role(request.user, {"admin", "devrel", "speaker"}):
            return view_func(request, *args, **kwargs)
        return redirect("/explore/")

    return _wrapped

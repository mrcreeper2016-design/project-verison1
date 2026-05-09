"""Login / logout + lockout + audit.

Password-reset and email-verification views live in ``.password`` and
``.email`` (added in Phase 3). Keeping this module focused on the hot
path of interactive sign-in.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from django.contrib.auth import get_user_model
from django.db.models import Q

from ..forms import LoginForm
from ..models import AuditLog
from ..services import audit, lockout


def _safe_next(request: HttpRequest, fallback: str) -> str:
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _client_ip(request: HttpRequest) -> str | None:
    return request.META.get("REMOTE_ADDR") or None


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect(_safe_next(request, settings.LOGIN_REDIRECT_URL))

    form = LoginForm(request.POST or None)
    lockout_remaining = 0
    error_message: str | None = None

    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        password = form.cleaned_data["password"]
        ip = _client_ip(request)

        if lockout.is_locked(username):
            lockout_remaining = lockout.seconds_until_unlock(username)
            audit.log(
                action=AuditLog.ACTION_LOGIN_FAILED,
                actor=None,
                request=request,
                target_type="Username",
                target_id=username[:64],
                metadata={"reason": "locked_out", "remaining_sec": lockout_remaining},
            )
            error_message = (
                f"Слишком много неудачных попыток. Попробуйте снова через {lockout_remaining} секунд."
            )
        else:
            user = authenticate(request, username=username, password=password)
            if user is None:
                # The backend returns None for inactive users too. Re-check
                # the raw user to give a specific "please verify email"
                # hint when password IS correct but the account is pending
                # verification — this is safe because the attacker would
                # already need to know a valid password.
                UserModel = get_user_model()
                candidate = (
                    UserModel.objects.filter(
                        Q(username__iexact=username) | Q(email__iexact=username)
                    )
                    .first()
                )
                is_pending_verify = (
                    candidate is not None
                    and not candidate.is_active
                    and candidate.check_password(password)
                    and not getattr(getattr(candidate, "profile", None), "email_verified", True)
                )

                if is_pending_verify:
                    # Don't burn a lockout slot for "correct password,
                    # just unverified" — otherwise a forgetful user who
                    # hits login 6 times gets locked out.
                    audit.log(
                        action=AuditLog.ACTION_LOGIN_FAILED,
                        actor=None,
                        request=request,
                        target_type="User",
                        target_id=str(candidate.pk),
                        metadata={"reason": "email_not_verified"},
                    )
                    error_message = (
                        "Email не подтверждён. Проверьте почту и перейдите по ссылке из письма."
                    )
                else:
                    lockout.register_attempt(username, ip, success=False)
                    audit.log(
                        action=AuditLog.ACTION_LOGIN_FAILED,
                        actor=None,
                        request=request,
                        target_type="Username",
                        target_id=username[:64],
                        metadata={"reason": "invalid_credentials"},
                    )
                    if lockout.is_locked(username):
                        lockout_remaining = lockout.seconds_until_unlock(username)
                        audit.log(
                            action=AuditLog.ACTION_LOCKOUT_TRIGGERED,
                            actor=None,
                            request=request,
                            target_type="Username",
                            target_id=username[:64],
                            metadata={"window_sec": settings.ACCOUNTS_LOCKOUT_WINDOW_SECONDS},
                        )
                        error_message = (
                            f"Слишком много неудачных попыток. Попробуйте снова через {lockout_remaining} секунд."
                        )
                    else:
                        error_message = "Неверное имя пользователя или пароль"
            elif not user.is_active:
                audit.log(
                    action=AuditLog.ACTION_LOGIN_FAILED,
                    actor=None,
                    request=request,
                    target_type="User",
                    target_id=str(user.pk),
                    metadata={"reason": "inactive"},
                )
                error_message = "Аккаунт отключён. Обратитесь к администратору."
            else:
                lockout.register_attempt(username, ip, success=True)
                auth_login(request, user)
                audit.log(
                    action=AuditLog.ACTION_LOGIN_SUCCESS,
                    actor=user,
                    request=request,
                    target=user,
                )
                return redirect(_safe_next(request, settings.LOGIN_REDIRECT_URL))

    context = {
        "form": form,
        "error_message": error_message,
        "lockout_remaining": lockout_remaining,
        "next": request.GET.get("next", ""),
    }
    return render(request, "accounts/login.html", context)


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    """POST logs the user out. GET renders a confirm page to avoid CSRF via links."""
    if request.method == "POST":
        user = request.user if request.user.is_authenticated else None
        if user is not None:
            audit.log(action=AuditLog.ACTION_LOGOUT, actor=user, request=request, target=user)
        auth_logout(request)
        messages.info(request, "Вы вышли из системы.")
        return redirect(reverse("accounts:login"))
    return render(request, "accounts/logout_confirm.html", {})

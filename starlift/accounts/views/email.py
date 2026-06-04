"""Email verification (one-shot links)."""
from __future__ import annotations

import hashlib

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from ..models import AuditLog, EmailVerification
from ..services import audit


@never_cache
@require_http_methods(["GET"])
def verify_email_view(request: HttpRequest, token: str) -> HttpResponse:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record = EmailVerification.objects.filter(token_hash=token_hash).first()

    if record is None or record.used_at is not None or record.expires_at < timezone.now():
        return render(request, "accounts/verify_email_expired.html", status=410)

    user = record.user

    # Guard against races: another user grabbing this email between request and confirm.
    User = get_user_model()
    if User.objects.filter(email__iexact=record.new_email).exclude(pk=user.pk).exists():
        return render(
            request,
            "accounts/verify_email_expired.html",
            {"reason": "email_taken"},
            status=409,
        )

    # For the initial registration flow `new_email == user.email` so the
    # swap is a no-op; for email-change it's a real rename.
    was_initial_verification = (not user.is_active) and (user.email.lower() == record.new_email.lower())
    user.email = record.new_email
    fields_to_update = ["email"]
    if not user.is_active:
        # Self-registered guests are created with is_active=False and only
        # become logginable after clicking the verification link.
        user.is_active = True
        fields_to_update.append("is_active")
    user.save(update_fields=fields_to_update)

    profile = user.profile
    profile.pending_email = None
    profile.email_verified = True
    profile.save(update_fields=["pending_email", "email_verified", "updated_at"])

    record.used_at = timezone.now()
    record.save(update_fields=["used_at"])

    if was_initial_verification:
        audit.log(
            action=AuditLog.ACTION_EMAIL_VERIFIED,
            actor=user,
            request=request,
            target=user,
            metadata={"email": record.new_email, "flow": "registration"},
        )
    else:
        audit.log(
            action=AuditLog.ACTION_EMAIL_CHANGE_CONFIRMED,
            actor=user,
            request=request,
            target=user,
            metadata={"new_email": record.new_email},
        )

    if request.user.is_authenticated and request.user.pk == user.pk:
        messages.success(request, "Email подтверждён и обновлён.")
        return redirect(reverse("accounts:profile"))

    if was_initial_verification:
        # Auto-login the freshly verified guest and send them straight to the
        # speaker-application form — that's the next required step before
        # they can do anything member-level.
        user.backend = "accounts.auth_backends.UsernameOrEmailBackend"
        auth_login(request, user)
        if profile.role == profile.ROLE_GUEST:
            messages.success(request, "Email подтверждён. Заполните профиль спикера для отправки заявки.")
            return redirect(reverse("accounts:speaker_application_form"))
        return redirect("/")
    return render(
        request,
        "accounts/verify_email_done.html",
        {"email": record.new_email, "initial_verification": was_initial_verification},
    )

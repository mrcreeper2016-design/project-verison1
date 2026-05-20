"""Self-service open registration (creates a `guest` account).

Flow:
1. Visitor fills the form at /auth/register/.
2. We create User(is_active=False) + UserProfile(role=guest, email_verified=False)
   and issue an EmailVerification record whose new_email == user's email.
3. An activation email is sent. The existing verify_email_view consumes
   the token, flipping is_active and email_verified to True.
4. After verify the visitor can log in; by default they land on /explore/
   (a read-only, member-agnostic page) until an admin promotes them.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from ..decorators import anonymous_required
from ..forms import RegisterForm
from ..models import AuditLog, EmailVerification, UserProfile
from ..services import audit, email as email_svc, tokens as token_svc
from django.contrib.auth import get_user_model

User = get_user_model()


@anonymous_required()
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def register_view(request: HttpRequest) -> HttpResponse:
    """Open registration — no invite needed, produces a `guest` account."""
    form = RegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data.get("first_name", ""),
                last_name=form.cleaned_data.get("last_name", ""),
            )
            # Block login until the user clicks the verification link.
            user.is_active = False
            user.save(update_fields=["is_active"])

            # Signal created the profile with role=guest by default — just
            # make the intent explicit and reset verification flags.
            now = timezone.now()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.ROLE_GUEST
            profile.email_verified = False
            profile.pending_email = None
            profile.pdn_consent_at = now
            profile.policy_accepted_at = now
            profile.consent_doc_version = settings.LEGAL_DOC_VERSION
            profile.save(update_fields=[
                "role",
                "email_verified",
                "pending_email",
                "pdn_consent_at",
                "policy_accepted_at",
                "consent_doc_version",
                "updated_at",
            ])

            raw = token_svc.make_token()
            ttl_hours = getattr(settings, "ACCOUNTS_EMAIL_CHANGE_TTL_HOURS", 24)
            EmailVerification.objects.create(
                user=user,
                new_email=user.email,
                token_hash=token_svc.hash_token(raw),
                expires_at=timezone.now() + timedelta(hours=ttl_hours),
            )

            audit.log(
                action=AuditLog.ACTION_GUEST_REGISTERED,
                actor=user,
                request=request,
                target=user,
                metadata={"email": user.email, "username": user.username},
            )
            audit.log(
                action=AuditLog.ACTION_CONSENT_GIVEN,
                actor=user,
                request=request,
                target=user,
                metadata={"doc_version": settings.LEGAL_DOC_VERSION},
            )

        try:
            email_svc.send_registration_verification(
                to=user.email,
                raw_token=raw,
                username=user.username,
            )
        except Exception:
            # Never leak the verification link in the UI; if the mailer is
            # broken the admin should diagnose from the audit log.
            messages.warning(
                request,
                "Аккаунт создан, но письмо не удалось отправить. Свяжитесь с администратором.",
            )
        return redirect(reverse("accounts:register_pending") + f"?email={user.email}")

    return render(
        request,
        "accounts/register.html",
        {"form": form, "legal_doc_version": settings.LEGAL_DOC_VERSION},
    )


@anonymous_required()
@never_cache
@require_http_methods(["GET"])
def register_pending_view(request: HttpRequest) -> HttpResponse:
    """Shown after a successful POST to /auth/register/.

    The page is deliberately generic — we never confirm/deny whether the
    email actually exists in our database beyond the fact that the form
    was submitted.
    """
    email = request.GET.get("email", "")
    return render(request, "accounts/register_pending.html", {"email": email})

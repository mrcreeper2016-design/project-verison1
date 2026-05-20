"""Admin-side invite issuance + public accept flow.

The admin console list + issue/revoke operations live here; the accept
flow (public) is also here since it consumes the same model.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from ..decorators import role_required
from ..forms import InviteCreateForm, InviteSignupForm
from ..models import AuditLog, Invite, UserProfile
from ..services import audit, email as email_svc, tokens as token_svc
from ..services.speaker_avatar import seed_user_profile_avatar_from_linked_speaker


User = get_user_model()


@role_required("admin")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def invites_view(request: HttpRequest) -> HttpResponse:
    """List + create invites (admin only)."""
    now = timezone.now()
    if request.method == "POST":
        form = InviteCreateForm(request.POST)
        if form.is_valid():
            ttl_days = getattr(settings, "ACCOUNTS_INVITE_TTL_DAYS", 7)
            raw = token_svc.make_token()
            invite: Invite = form.save(commit=False)
            invite.created_by = request.user
            invite.token_hash = token_svc.hash_token(raw)
            invite.expires_at = now + timedelta(days=ttl_days)
            invite.save()

            audit.log(
                action=AuditLog.ACTION_INVITE_CREATED,
                actor=request.user,
                request=request,
                target=invite,
                metadata={"email": invite.email, "role": invite.role},
            )

            if form.cleaned_data.get("send_email", True):
                try:
                    email_svc.send_invite_email(
                        to=invite.email,
                        raw_token=raw,
                        role=invite.get_role_display(),
                        inviter_name=request.user.get_full_name() or request.user.username,
                    )
                    messages.success(request, f"Инвайт создан и отправлен на {invite.email}.")
                except Exception:
                    messages.warning(
                        request,
                        f"Инвайт создан, но письмо не отправлено. Поделитесь ссылкой вручную:\n"
                        f"{request.build_absolute_uri(reverse('accounts:invite_accept', args=[raw]))}",
                    )
            else:
                messages.success(
                    request,
                    f"Инвайт создан. Ссылка: {request.build_absolute_uri(reverse('accounts:invite_accept', args=[raw]))}",
                )
            return redirect(reverse("accounts:invites"))
    else:
        form = InviteCreateForm()

    status_filter = request.GET.get("status", "active")
    qs = Invite.objects.select_related("created_by", "speaker", "consumed_by").order_by("-created_at")
    if status_filter == "active":
        qs = qs.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now)
    elif status_filter == "consumed":
        qs = qs.filter(used_at__isnull=False)
    elif status_filter == "revoked":
        qs = qs.filter(revoked_at__isnull=False)
    elif status_filter == "expired":
        qs = qs.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__lte=now)

    return render(
        request,
        "accounts/console/invites.html",
        {
            "form": form,
            "invites": qs[:200],
            "status_filter": status_filter,
            "now": now,
        },
    )


@role_required("admin")
@require_http_methods(["POST"])
def invite_revoke_view(request: HttpRequest, invite_id) -> HttpResponse:
    invite = get_object_or_404(Invite, pk=invite_id)
    if invite.revoked_at or invite.used_at:
        messages.info(request, "Инвайт уже неактивен.")
        return redirect(reverse("accounts:invites"))
    invite.revoked_at = timezone.now()
    invite.save(update_fields=["revoked_at"])
    audit.log(
        action=AuditLog.ACTION_INVITE_REVOKED,
        actor=request.user,
        request=request,
        target=invite,
        metadata={"email": invite.email},
    )
    messages.success(request, "Инвайт отозван.")
    return redirect(reverse("accounts:invites"))


@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def invite_accept_view(request: HttpRequest, token: str) -> HttpResponse:
    """Public invite landing: validate token, create user, log them in."""
    token_hash = token_svc.hash_token(token)
    invite = Invite.objects.filter(token_hash=token_hash).select_related("speaker").first()

    if invite is None or not invite.is_active:
        return render(request, "accounts/invite_invalid.html", status=410)

    if request.method == "POST":
        form = InviteSignupForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Re-check atomically: guard against double-submit.
                    invite_fresh = Invite.objects.select_for_update().get(pk=invite.pk)
                    if not invite_fresh.is_active:
                        raise ValidationError("Invite no longer active")

                    user = User.objects.create_user(
                        username=form.cleaned_data["username"],
                        email=invite_fresh.email,
                        password=form.cleaned_data["password1"],
                        first_name=form.cleaned_data.get("first_name", ""),
                        last_name=form.cleaned_data.get("last_name", ""),
                    )
                    user.is_active = True
                    user.save(update_fields=["is_active"])

                    now = timezone.now()
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = invite_fresh.role
                    profile.email_verified = True  # invite arrived at this email
                    profile.pdn_consent_at = now
                    profile.policy_accepted_at = now
                    profile.consent_doc_version = settings.LEGAL_DOC_VERSION
                    profile.save(update_fields=[
                        "role",
                        "email_verified",
                        "pdn_consent_at",
                        "policy_accepted_at",
                        "consent_doc_version",
                        "updated_at",
                    ])

                    if invite_fresh.speaker_id and invite_fresh.role == UserProfile.ROLE_SPEAKER:
                        speaker = invite_fresh.speaker
                        if speaker is not None and speaker.user_id is None:
                            speaker.user = user
                            speaker.save(update_fields=["user"])
                            seed_user_profile_avatar_from_linked_speaker(speaker, user)

                    invite_fresh.used_at = timezone.now()
                    invite_fresh.consumed_by = user
                    invite_fresh.save(update_fields=["used_at", "consumed_by"])

                    audit.log(
                        action=AuditLog.ACTION_INVITE_CONSUMED,
                        actor=user,
                        request=request,
                        target=invite_fresh,
                        metadata={"email": invite_fresh.email, "role": invite_fresh.role},
                    )
                    audit.log(
                        action=AuditLog.ACTION_CONSENT_GIVEN,
                        actor=user,
                        request=request,
                        target=user,
                        metadata={"doc_version": settings.LEGAL_DOC_VERSION},
                    )

                user.backend = "accounts.auth_backends.UsernameOrEmailBackend"
                auth_login(request, user)
                messages.success(request, "Регистрация завершена. Добро пожаловать!")
                return redirect(settings.LOGIN_REDIRECT_URL)
            except ValidationError:
                return render(request, "accounts/invite_invalid.html", status=410)
    else:
        form = InviteSignupForm()

    return render(
        request,
        "accounts/invite_accept.html",
        {
            "form": form,
            "invite": invite,
            "legal_doc_version": settings.LEGAL_DOC_VERSION,
        },
    )

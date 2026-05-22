"""Speaker self-service profile: edit name / bio / email, change password.

The template is a real form-based page; email changes require verification
via ``views.email.verify_email_view``.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from starlift.models import Speaker

from ..forms import EmailChangeForm, ProfileEditForm, SpeakerProfileMainForm
from ..models import AuditLog, EmailVerification, UserProfile
from ..services import audit, email as email_svc, tokens as token_svc
from ..services.speaker_avatar import backfill_profile_avatar_if_empty


def _get_or_create_profile(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"role": UserProfile.ROLE_SPEAKER, "email_verified": False},
    )
    return profile


def _speaker_main_form(user, profile, linked_speaker):
    """Форма «Основное»: для привязанного спикера — описание карточки; иначе поле «О себе»."""
    if profile.role == UserProfile.ROLE_SPEAKER and linked_speaker is not None:
        return SpeakerProfileMainForm(
            initial={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "company": linked_speaker.sub or "",
                "description": linked_speaker.stack or "",
            }
        )
    return ProfileEditForm(
        initial={
            "first_name": user.first_name,
            "last_name": user.last_name,
            "company": profile.company,
            "bio": profile.bio,
        }
    )


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def profile_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    profile = _get_or_create_profile(user)
    linked_speaker = Speaker.objects.filter(user=user).first()
    is_speaker_role = profile.role == UserProfile.ROLE_SPEAKER

    def _speaker_name() -> str:
        return f"{user.first_name} {user.last_name}".strip() or user.username

    if linked_speaker and request.method == "GET":
        if backfill_profile_avatar_if_empty(linked_speaker, user):
            profile.refresh_from_db()

    if request.method == "GET":
        form = _speaker_main_form(user, profile, linked_speaker)
    else:
        action = request.POST.get("action", "profile")
        if action != "profile":
            messages.error(request, "Неизвестное действие.")
            return redirect(reverse("accounts:profile"))

        speaker_linked = is_speaker_role and linked_speaker is not None
        if speaker_linked:
            form = SpeakerProfileMainForm(request.POST, request.FILES)
        else:
            form = ProfileEditForm(
                request.POST,
                request.FILES,
                initial={
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "bio": profile.bio,
                },
            )

        if form.is_valid():
            changes: dict = {}
            if form.cleaned_data.get("first_name") != user.first_name:
                changes["first_name"] = {"old": user.first_name, "new": form.cleaned_data["first_name"]}
                user.first_name = form.cleaned_data["first_name"]
            if form.cleaned_data.get("last_name") != user.last_name:
                changes["last_name"] = {"old": user.last_name, "new": form.cleaned_data["last_name"]}
                user.last_name = form.cleaned_data["last_name"]

            avatar_file = form.cleaned_data.get("avatar")
            if avatar_file:
                profile.avatar = avatar_file
                changes["avatar"] = {"updated": True}

            profile_update_fields = ["updated_at"]
            if speaker_linked:
                desc = form.cleaned_data.get("description") or ""
                company = form.cleaned_data.get("company") or ""
                if desc != (linked_speaker.stack or ""):
                    changes["speaker.stack"] = True
                if company != (linked_speaker.sub or ""):
                    changes["speaker.sub"] = True
                if desc != (profile.bio or ""):
                    changes["bio_len"] = {"old": len(profile.bio or ""), "new": len(desc)}
                profile.bio = desc
                profile_update_fields.append("bio")
                linked_speaker.stack = desc
                linked_speaker.bio = desc
                linked_speaker.sub = company
                linked_speaker.name = _speaker_name()
                linked_speaker.save(update_fields=["name", "stack", "bio", "sub"])
            else:
                new_bio = form.cleaned_data.get("bio") or ""
                if new_bio != profile.bio:
                    changes["bio_len"] = {"old": len(profile.bio), "new": len(new_bio)}
                    profile.bio = new_bio
                    profile_update_fields.append("bio")
                new_company = form.cleaned_data.get("company") or ""
                if new_company != (profile.company or ""):
                    changes["company"] = {"old": profile.company, "new": new_company}
                    profile.company = new_company
                    profile_update_fields.append("company")
                if linked_speaker:
                    linked_speaker.name = _speaker_name()
                    linked_speaker.bio = profile.bio or ""
                    linked_speaker.save(update_fields=["name", "bio"])

            if changes:
                user.save(update_fields=["first_name", "last_name"])
                if "avatar" in changes:
                    profile_update_fields.append("avatar")
                profile.save(update_fields=profile_update_fields)

                audit.log(
                    action=AuditLog.ACTION_PROFILE_UPDATED,
                    actor=user,
                    request=request,
                    target=user,
                    metadata={"fields": list(changes.keys())},
                )
                messages.success(request, "Профиль обновлён.")
            else:
                messages.info(request, "Изменений не найдено.")
            return redirect(reverse("accounts:profile"))

    context = {
        "form": form,
        "profile": profile,
        "pending_email": profile.pending_email,
        "linked_speaker": linked_speaker,
        "is_speaker_role": is_speaker_role,
        "speaker_card_linked": is_speaker_role and linked_speaker is not None,
        "active": "settings",
    }
    return render(request, "accounts/profile.html", context)


@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def email_change_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    profile = _get_or_create_profile(user)

    form = EmailChangeForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_email = form.cleaned_data["new_email"]

        # Invalidate any existing unused verification requests.
        EmailVerification.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())

        raw = token_svc.make_token()
        ttl_hours = getattr(settings, "ACCOUNTS_EMAIL_CHANGE_TTL_HOURS", 24)
        EmailVerification.objects.create(
            user=user,
            new_email=new_email,
            token_hash=token_svc.hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=ttl_hours),
        )

        profile.pending_email = new_email
        profile.save(update_fields=["pending_email", "updated_at"])

        try:
            email_svc.send_email_change_verification(to=new_email, raw_token=raw, username=user.username)
        except Exception:
            messages.error(request, "Не удалось отправить письмо. Попробуйте позже.")
        else:
            audit.log(
                action=AuditLog.ACTION_EMAIL_CHANGE_REQUESTED,
                actor=user,
                request=request,
                target=user,
                metadata={"new_email": new_email},
            )
            messages.success(
                request,
                f"Ссылка для подтверждения отправлена на {new_email}. Email обновится после перехода по ссылке.",
            )
        return redirect(reverse("accounts:profile"))

    return render(request, "accounts/email_change.html", {"form": form, "profile": profile})


@login_required
@require_http_methods(["POST"])
def email_change_cancel_view(request: HttpRequest) -> HttpResponse:
    profile = _get_or_create_profile(request.user)
    if profile.pending_email:
        EmailVerification.objects.filter(user=request.user, used_at__isnull=True).update(used_at=timezone.now())
        profile.pending_email = None
        profile.save(update_fields=["pending_email", "updated_at"])
        messages.info(request, "Запрос на смену email отменён.")
    return redirect(reverse("accounts:profile"))

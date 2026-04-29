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
from starlift.forms import SpeakerSelfEditForm

from ..forms import EmailChangeForm, ProfileEditForm
from ..models import AuditLog, EmailVerification, UserProfile
from ..services import audit, email as email_svc, tokens as token_svc


def _get_or_create_profile(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={"role": UserProfile.ROLE_SPEAKER, "email_verified": False},
    )
    return profile


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

    if request.method == "POST":
        action = request.POST.get("action", "profile")
        form = ProfileEditForm(
            request.POST if action == "profile" else None,
            request.FILES if action == "profile" else None,
            initial={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "bio": profile.bio,
            },
        )
        speaker_form = SpeakerSelfEditForm(
            request.POST if action == "speaker_profile" else None,
            request.FILES if action == "speaker_profile" else None,
            instance=linked_speaker,
        )

        if action == "speaker_profile":
            if not is_speaker_role:
                messages.error(request, "Доступ к настройке профиля спикера запрещён.")
                return redirect(reverse("accounts:profile"))
            if not linked_speaker:
                messages.warning(
                    request,
                    "Профиль спикера ещё не привязан. Попросите администратора связать ваш аккаунт со спикером.",
                )
                return redirect(reverse("accounts:profile"))
            if speaker_form.is_valid():
                updated_speaker = speaker_form.save(commit=False)
                # Source of truth for these fields is the account profile.
                updated_speaker.name = _speaker_name()
                updated_speaker.bio = profile.bio or ""
                updated_speaker.save()
                messages.success(request, "Карточка спикера обновлена.")
                audit.log(
                    action=AuditLog.ACTION_PROFILE_UPDATED,
                    actor=user,
                    request=request,
                    target=user,
                    metadata={"fields": ["speaker.sub", "speaker.stack", "speaker.city", "speaker.status", "speaker.img"]},
                )
                return redirect(reverse("accounts:profile"))
        elif form.is_valid():
            changes: dict = {}
            if form.cleaned_data.get("first_name") != user.first_name:
                changes["first_name"] = {"old": user.first_name, "new": form.cleaned_data["first_name"]}
                user.first_name = form.cleaned_data["first_name"]
            if form.cleaned_data.get("last_name") != user.last_name:
                changes["last_name"] = {"old": user.last_name, "new": form.cleaned_data["last_name"]}
                user.last_name = form.cleaned_data["last_name"]
            new_bio = form.cleaned_data.get("bio") or ""
            if new_bio != profile.bio:
                changes["bio_len"] = {"old": len(profile.bio), "new": len(new_bio)}
                profile.bio = new_bio
            avatar_file = form.cleaned_data.get("avatar")
            if avatar_file:
                profile.avatar = avatar_file
                changes["avatar"] = {"updated": True}
            if changes:
                user.save(update_fields=["first_name", "last_name"])
                profile_update_fields = ["bio", "updated_at"]
                if "avatar" in changes:
                    profile_update_fields.append("avatar")
                profile.save(update_fields=profile_update_fields)
                if linked_speaker:
                    linked_speaker.name = _speaker_name()
                    linked_speaker.bio = profile.bio or ""
                    linked_speaker.save(update_fields=["name", "bio"])
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
    else:
        form = ProfileEditForm(initial={
            "first_name": user.first_name,
            "last_name": user.last_name,
            "bio": profile.bio,
        })
        speaker_form = SpeakerSelfEditForm(instance=linked_speaker)

    context = {
        "form": form,
        "profile": profile,
        "pending_email": profile.pending_email,
        "speaker_form": speaker_form,
        "linked_speaker": linked_speaker,
        "is_speaker_role": is_speaker_role,
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

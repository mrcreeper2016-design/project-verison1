"""Admin console: users list/detail, audit viewer, lockout release, link-speaker.

All endpoints are gated by `@role_required('admin')`. They audit every
mutating operation via `accounts.services.audit.log`.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from starlift.models import Event, EventRequest, Speaker, SpeakerApplication

from ..decorators import role_required
from ..models import AuditLog, LoginAttempt, UserProfile
from ..services import audit, lockout
from ..services.companies import ALLOWED_COMPANIES, is_allowed_company
from ..services.speaker_avatar import seed_user_profile_avatar_from_linked_speaker


User = get_user_model()


@role_required("admin")
@never_cache
@require_http_methods(["GET"])
def users_view(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    role_filter = request.GET.get("role", "")
    active_filter = request.GET.get("active", "")

    qs = (
        User.objects.select_related("profile")
        .annotate(recent_fails=Count(
            "id",
            filter=Q(username__in=[]),  # placeholder, real failures computed below
        ))
        .order_by("-date_joined")
    )
    if q:
        qs = qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
    if role_filter in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_DEVREL, UserProfile.ROLE_SPEAKER, UserProfile.ROLE_GUEST):
        qs = qs.filter(profile__role=role_filter)
    if active_filter == "active":
        qs = qs.filter(is_active=True)
    elif active_filter == "inactive":
        qs = qs.filter(is_active=False)

    paginator = Paginator(qs, 40)
    page = paginator.get_page(request.GET.get("page"))

    # Cheap per-page lockout indicator.
    locked_usernames = set()
    for u in page.object_list:
        if lockout.is_locked(u.username):
            locked_usernames.add(u.username)
    linked_speaker_user_ids = set(
        Speaker.objects.exclude(user__isnull=True).values_list("user_id", flat=True)
    )

    return render(
        request,
        "accounts/console/users.html",
        {
            "active": "users",
            "page": page,
            "q": q,
            "role_filter": role_filter,
            "active_filter": active_filter,
            "locked_usernames": locked_usernames,
            "linked_speaker_user_ids": linked_speaker_user_ids,
        },
    )


@role_required("admin")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def user_detail_view(request: HttpRequest, user_id: int) -> HttpResponse:
    target = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "unlock":
            removed = lockout.unlock(target.username, actor=request.user, request=request)
            messages.success(request, f"Lockout снят. Удалено записей о неудачных попытках: {removed}.")

        elif action == "toggle_active":
            target.is_active = not target.is_active
            target.save(update_fields=["is_active"])
            audit.log(
                action=AuditLog.ACTION_USER_ACTIVATED if target.is_active else AuditLog.ACTION_USER_DEACTIVATED,
                actor=request.user,
                request=request,
                target=target,
                metadata={"is_active": target.is_active},
            )
            messages.success(
                request,
                "Аккаунт включён." if target.is_active else "Аккаунт отключён (запрещён логин).",
            )

        elif action == "change_role":
            new_role = request.POST.get("role")
            if new_role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_DEVREL, UserProfile.ROLE_SPEAKER, UserProfile.ROLE_GUEST):
                if new_role != profile.role:
                    old_role = profile.role
                    profile.role = new_role
                    profile.save(update_fields=["role", "updated_at"])
                    # Use a dedicated action code when this is the canonical
                    # "approve guest → speaker" transition so admins can
                    # filter the audit log later.
                    is_promotion = (
                        old_role == UserProfile.ROLE_GUEST
                        and new_role == UserProfile.ROLE_SPEAKER
                    )
                    audit.log(
                        action=AuditLog.ACTION_GUEST_PROMOTED if is_promotion else AuditLog.ACTION_ROLE_CHANGED,
                        actor=request.user,
                        request=request,
                        target=target,
                        metadata={"from": old_role, "to": new_role},
                    )
                    auto_linked_speaker = None
                    if is_promotion and not Speaker.objects.filter(user=target).exists():
                        # Avoid duplicate speaker cards: when a parsed speaker
                        # already exists, auto-link it on an exact name match.
                        full_name = f"{target.first_name} {target.last_name}".strip()
                        candidate_names = []
                        if full_name:
                            candidate_names.append(full_name)
                        if target.username:
                            candidate_names.append(target.username)

                        for candidate in candidate_names:
                            matches = list(
                                Speaker.objects.filter(user__isnull=True, name__iexact=candidate)[:2]
                            )
                            if len(matches) == 1:
                                auto_linked_speaker = matches[0]
                                auto_linked_speaker.user = target
                                auto_linked_speaker.save(update_fields=["user"])
                                seed_user_profile_avatar_from_linked_speaker(auto_linked_speaker, target)
                                audit.log(
                                    action=AuditLog.ACTION_SPEAKER_LINKED,
                                    actor=request.user,
                                    request=request,
                                    target=target,
                                    metadata={
                                        "speaker_id": auto_linked_speaker.pk,
                                        "speaker_name": auto_linked_speaker.name,
                                        "mode": "auto_match_on_promotion",
                                    },
                                )
                                break
                    if is_promotion:
                        messages.success(
                            request,
                            f"Пользователь подтверждён и получил роль спикера.",
                        )
                        if auto_linked_speaker:
                            messages.success(
                                request,
                                f"Автоматически привязан существующий профиль спикера: «{auto_linked_speaker.name}».",
                            )
                        else:
                            messages.info(
                                request,
                                "Профиль спикера не привязан автоматически. При необходимости свяжите вручную в блоке «Связь со спикером».",
                            )
                    else:
                        messages.success(request, f"Роль обновлена: {profile.get_role_display()}.")
            else:
                messages.error(request, "Неизвестная роль.")

        elif action == "link_speaker":
            speaker_id = request.POST.get("speaker_id")
            if not speaker_id:
                # unlink
                linked = Speaker.objects.filter(user=target).first()
                if linked:
                    linked.user = None
                    linked.save(update_fields=["user"])
                    audit.log(
                        action=AuditLog.ACTION_SPEAKER_UNLINKED,
                        actor=request.user,
                        request=request,
                        target=target,
                        metadata={"speaker_id": linked.pk, "speaker_name": linked.name},
                    )
                    messages.success(request, "Связь со спикером снята.")
            else:
                try:
                    with transaction.atomic():
                        speaker = Speaker.objects.select_for_update().get(pk=speaker_id)
                        if speaker.user_id and speaker.user_id != target.pk:
                            messages.error(
                                request,
                                f"Этот спикер уже связан с пользователем {speaker.user.username}.",
                            )
                        else:
                            Speaker.objects.filter(user=target).exclude(pk=speaker.pk).update(
                                user=None,
                                status=Speaker.STATUS_UNAUTHORIZED,
                            )
                            speaker.user = target
                            speaker.save(update_fields=["user"])
                            seed_user_profile_avatar_from_linked_speaker(speaker, target)
                            audit.log(
                                action=AuditLog.ACTION_SPEAKER_LINKED,
                                actor=request.user,
                                request=request,
                                target=target,
                                metadata={"speaker_id": speaker.pk, "speaker_name": speaker.name},
                            )
                            messages.success(request, f"Связан со спикером «{speaker.name}».")
                except Speaker.DoesNotExist:
                    messages.error(request, "Спикер не найден.")
        elif action == "set_company":
            new_company = (request.POST.get("company") or "").strip()
            if not is_allowed_company(new_company):
                messages.error(request, "Недопустимое значение компании.")
            else:
                old_company = profile.company
                if new_company != old_company:
                    profile.company = new_company
                    profile.save(update_fields=["company", "updated_at"])
                    audit.log(
                        action=AuditLog.ACTION_PROFILE_UPDATED,
                        actor=request.user,
                        request=request,
                        target=target,
                        metadata={"field": "company", "from": old_company, "to": new_company},
                    )
                    messages.success(request, "Компания обновлена.")

        elif action == "delete_guest":
            if profile.role != UserProfile.ROLE_GUEST:
                messages.error(request, "Удаление разрешено только для пользователей с ролью «Гость».")
            else:
                username = target.username
                target_id = target.pk
                audit.log(
                    action=AuditLog.ACTION_GUEST_DELETED,
                    actor=request.user,
                    request=request,
                    target=target,
                    metadata={"username": username, "user_id": target_id},
                )
                target.delete()
                messages.success(request, f"Гостевой пользователь @{username} удалён.")
                return redirect(reverse("accounts:users"))
        else:
            messages.error(request, "Неизвестное действие.")

        # Allow an inline form on the users list to bring the admin back to the
        # list (with the message) instead of jumping into the detail card.
        next_url = request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(reverse("accounts:user_detail", args=[target.pk]))

    linked_speaker = Speaker.objects.filter(user=target).first()
    available_speakers = Speaker.objects.filter(user__isnull=True).order_by("name")[:500]
    recent_attempts = LoginAttempt.objects.filter(username_or_email=target.username.lower()).order_by("-created_at")[:20]
    recent_events = AuditLog.objects.filter(Q(actor=target) | Q(target_type="User", target_id=str(target.pk))).order_by("-created_at")[:40]

    return render(
        request,
        "accounts/console/user_detail.html",
        {
            "active": "users",
            "target": target,
            "profile": profile,
            "linked_speaker": linked_speaker,
            "available_speakers": available_speakers,
            "recent_attempts": recent_attempts,
            "recent_events": recent_events,
            "is_locked": lockout.is_locked(target.username),
            "allowed_companies": ALLOWED_COMPANIES,
        },
    )


@role_required("admin")
@never_cache
@require_http_methods(["GET"])
def audit_view(request: HttpRequest) -> HttpResponse:
    q = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()

    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    if action:
        qs = qs.filter(action=action)
    if q:
        qs = qs.filter(
            Q(actor__username__icontains=q)
            | Q(target_id__icontains=q)
            | Q(target_type__icontains=q)
            | Q(ip__icontains=q)
        )

    paginator = Paginator(qs, 100)
    page = paginator.get_page(request.GET.get("page"))
    known_actions = sorted(set(AuditLog.objects.values_list("action", flat=True).distinct()))

    return render(
        request,
        "accounts/console/audit.html",
        {
            "active": "audit",
            "page": page,
            "q": q,
            "action": action,
            "known_actions": known_actions,
        },
    )


def _devrel_visible_applications(actor) -> "QuerySet[SpeakerApplication]":
    """SpeakerApplication queryset filtered per actor's routing rules.

    Admin/superuser sees all. DevRel sees applications whose `company`
    matches their `UserProfile.company` (case-insensitive) plus all
    applications with empty company ("общий пул"). Other roles get nothing.
    """
    qs = SpeakerApplication.objects.select_related("applicant", "reviewed_by").order_by("-created_at")
    if actor.is_superuser:
        return qs
    profile = getattr(actor, "profile", None)
    if profile is None:
        return SpeakerApplication.objects.none()
    if profile.role == UserProfile.ROLE_ADMIN:
        return qs
    if profile.role == UserProfile.ROLE_DEVREL:
        actor_company = (profile.company or "").strip()
        if actor_company:
            return qs.filter(Q(company__iexact=actor_company) | Q(company=""))
        return qs.filter(company="")
    return SpeakerApplication.objects.none()


@role_required("admin", "devrel")
@never_cache
@require_http_methods(["GET"])
def event_requests_view(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "pending")
    kind = request.GET.get("kind", "")

    er_qs = EventRequest.objects.select_related("speaker", "event", "reviewed_by").order_by("-created_at")
    if status in (EventRequest.STATUS_PENDING, EventRequest.STATUS_APPROVED, EventRequest.STATUS_REJECTED):
        er_qs = er_qs.filter(status=status)
    if kind in (EventRequest.KIND_CREATE, EventRequest.KIND_JOIN):
        er_qs = er_qs.filter(kind=kind)

    apps_qs = _devrel_visible_applications(request.user)
    if status in (SpeakerApplication.STATUS_PENDING, SpeakerApplication.STATUS_APPROVED, SpeakerApplication.STATUS_REJECTED):
        apps_qs = apps_qs.filter(status=status)

    show_event_requests = kind in ("", EventRequest.KIND_CREATE, EventRequest.KIND_JOIN)
    show_applications = kind in ("", "speaker")

    items = []
    if show_event_requests:
        for r in er_qs:
            items.append({"kind": "event_request", "obj": r, "created_at": r.created_at})
    if show_applications:
        for a in apps_qs:
            items.append({"kind": "speaker_application", "obj": a, "created_at": a.created_at})
    items.sort(key=lambda x: x["created_at"], reverse=True)

    paginator = Paginator(items, 50)
    page = paginator.get_page(request.GET.get("page"))

    pending_count = (
        EventRequest.objects.filter(status=EventRequest.STATUS_PENDING).count()
        + _devrel_visible_applications(request.user).filter(status=SpeakerApplication.STATUS_PENDING).count()
    )

    return render(
        request,
        "accounts/console/event_requests.html",
        {
            "active": "event_requests",
            "page": page,
            "status": status,
            "kind": kind,
            "pending_count": pending_count,
        },
    )


@role_required("admin", "devrel")
@never_cache
@require_http_methods(["POST"])
@csrf_protect
def event_request_action_view(request: HttpRequest, request_id: int, action: str) -> HttpResponse:
    req = get_object_or_404(EventRequest, pk=request_id)
    if req.status != EventRequest.STATUS_PENDING:
        messages.error(request, "Заявка уже обработана.")
        return redirect(reverse("accounts:event_requests"))

    if action == "approve":
        with transaction.atomic():
            if req.kind == EventRequest.KIND_CREATE:
                pd = req.proposed_event_date
                _RU = {1:'января',2:'февраля',3:'марта',4:'апреля',5:'мая',6:'июня',7:'июля',8:'августа',9:'сентября',10:'октября',11:'ноября',12:'декабря'}
                human_date = f"{pd.day} {_RU[pd.month]} {pd.year}" if pd else None
                event = Event.objects.create(
                    title=req.proposed_title,
                    description=req.proposed_description or None,
                    event_date=pd,
                    date=human_date,
                    location=req.proposed_location or None,
                    link=req.proposed_link or None,
                    source='self',
                    status='past' if (pd and pd < timezone.now().date()) else 'future',
                )
                event.speakers.add(req.speaker)
                req.event = event
            elif req.kind == EventRequest.KIND_JOIN and req.event:
                req.event.speakers.add(req.speaker)
            req.status = EventRequest.STATUS_APPROVED
            req.reviewed_at = timezone.now()
            req.reviewed_by = request.user
            req.save()
            audit.log(
                action="event_request_approved",
                actor=request.user,
                request=request,
                target=req.speaker.user if req.speaker.user_id else None,
                metadata={"request_id": req.id, "kind": req.kind, "event_id": req.event_id},
            )
        messages.success(request, "Заявка одобрена.")

    elif action == "reject":
        reason = (request.POST.get("rejection_reason") or "").strip()
        if not reason:
            messages.error(request, "Укажите причину отклонения.")
            return redirect(reverse("accounts:event_requests"))
        req.status = EventRequest.STATUS_REJECTED
        req.rejection_reason = reason
        req.reviewed_at = timezone.now()
        req.reviewed_by = request.user
        req.save()
        audit.log(
            action="event_request_rejected",
            actor=request.user,
            request=request,
            target=req.speaker.user if req.speaker.user_id else None,
            metadata={"request_id": req.id, "kind": req.kind, "reason": reason},
        )
        messages.success(request, "Заявка отклонена.")
    else:
        messages.error(request, "Неизвестное действие.")

    return redirect(reverse("accounts:event_requests") + f"?status={request.POST.get('return_status', 'pending')}")


def _check_application_access(actor, application: SpeakerApplication):
    """Return True if actor may view/act on `application`."""
    visible_ids = _devrel_visible_applications(actor).values_list("pk", flat=True)
    return application.pk in set(visible_ids)


@role_required("admin", "devrel")
@never_cache
@require_http_methods(["GET"])
def speaker_application_detail_view(request: HttpRequest, application_id: int) -> HttpResponse:
    app = get_object_or_404(SpeakerApplication.objects.select_related("applicant"), pk=application_id)
    if not _check_application_access(request.user, app):
        return redirect(reverse("accounts:event_requests"))

    available_speakers = Speaker.objects.filter(user__isnull=True).order_by("name")[:500]
    return render(
        request,
        "accounts/console/speaker_application_detail.html",
        {
            "active": "event_requests",
            "application": app,
            "available_speakers": available_speakers,
        },
    )


@role_required("admin", "devrel")
@never_cache
@csrf_protect
@require_http_methods(["POST"])
def speaker_application_action_view(request: HttpRequest, application_id: int, action: str) -> HttpResponse:
    app = get_object_or_404(SpeakerApplication.objects.select_related("applicant"), pk=application_id)
    if not _check_application_access(request.user, app):
        return redirect(reverse("accounts:event_requests"))

    if app.status != SpeakerApplication.STATUS_PENDING:
        messages.error(request, "Заявка уже обработана.")
        return redirect(reverse("accounts:event_requests"))

    applicant = app.applicant
    profile, _ = UserProfile.objects.get_or_create(user=applicant)

    if action == "approve":
        mode = request.POST.get("mode", "create")
        with transaction.atomic():
            if mode == "link":
                speaker_id = request.POST.get("speaker_id")
                if not speaker_id:
                    messages.error(request, "Выберите спикерскую карточку для привязки.")
                    return redirect(reverse("accounts:speaker_application_detail", args=[app.pk]))
                try:
                    speaker = Speaker.objects.select_for_update().get(pk=speaker_id)
                except Speaker.DoesNotExist:
                    messages.error(request, "Спикер не найден.")
                    return redirect(reverse("accounts:speaker_application_detail", args=[app.pk]))
                if speaker.user_id and speaker.user_id != applicant.pk:
                    messages.error(request, f"Эта карточка уже привязана к {speaker.user.username}.")
                    return redirect(reverse("accounts:speaker_application_detail", args=[app.pk]))
                speaker.user = applicant
                speaker.save(update_fields=["user"])
                seed_user_profile_avatar_from_linked_speaker(speaker, applicant)
                resulting_speaker = speaker
            else:
                full_name = f"{applicant.first_name} {applicant.last_name}".strip() or applicant.username
                resulting_speaker = Speaker.objects.create(
                    name=full_name,
                    sub=app.company,
                    stack=app.stack,
                    city=app.city,
                    bio=app.description,
                    user=applicant,
                )

            old_role = profile.role
            profile.role = UserProfile.ROLE_SPEAKER
            profile.save(update_fields=["role", "updated_at"])

            app.status = SpeakerApplication.STATUS_APPROVED
            app.reviewed_at = timezone.now()
            app.reviewed_by = request.user
            app.resulting_speaker = resulting_speaker
            app.save(update_fields=["status", "reviewed_at", "reviewed_by", "resulting_speaker"])

            audit.log(
                action=AuditLog.ACTION_SPEAKER_APPLICATION_APPROVED,
                actor=request.user,
                request=request,
                target=applicant,
                metadata={
                    "application_id": app.pk,
                    "speaker_id": resulting_speaker.pk,
                    "mode": mode,
                },
            )
            audit.log(
                action=AuditLog.ACTION_ROLE_CHANGED,
                actor=request.user,
                request=request,
                target=applicant,
                metadata={"from": old_role, "to": UserProfile.ROLE_SPEAKER},
            )
            audit.log(
                action=AuditLog.ACTION_SPEAKER_LINKED,
                actor=request.user,
                request=request,
                target=applicant,
                metadata={
                    "speaker_id": resulting_speaker.pk,
                    "speaker_name": resulting_speaker.name,
                    "mode": "application_" + mode,
                },
            )
        messages.success(request, f"Заявка одобрена. {applicant.username} теперь спикер.")

    elif action == "reject":
        reason = (request.POST.get("rejection_reason") or "").strip()
        if not reason:
            messages.error(request, "Укажите причину отклонения.")
            return redirect(reverse("accounts:speaker_application_detail", args=[app.pk]))
        app.status = SpeakerApplication.STATUS_REJECTED
        app.rejection_reason = reason
        app.reviewed_at = timezone.now()
        app.reviewed_by = request.user
        app.save(update_fields=["status", "rejection_reason", "reviewed_at", "reviewed_by"])
        audit.log(
            action=AuditLog.ACTION_SPEAKER_APPLICATION_REJECTED,
            actor=request.user,
            request=request,
            target=applicant,
            metadata={"application_id": app.pk, "reason": reason},
        )
        messages.success(request, "Заявка отклонена.")
    else:
        messages.error(request, "Неизвестное действие.")

    return redirect(reverse("accounts:event_requests"))

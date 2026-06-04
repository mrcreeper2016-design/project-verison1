"""JSON API for the header bell + drawer support pane."""
from __future__ import annotations

import json
import re

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from accounts.services import audit

from ..models import SupportTicket, SupportMessage
from ..services import notifications
from ..services.avatars import avatar_url_for_user


def _is_admin(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


def _preview(text: str, limit: int = 80) -> str:
    if not text:
        return ""
    one_line = re.sub(r"\s+", " ", text).strip()
    if len(one_line) <= limit:
        return one_line
    cut = one_line[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut + "…"


def _sender_name(m: SupportMessage, ticket: SupportTicket) -> str:
    if m.sender_user_id:
        return m.sender_user.get_full_name() or m.sender_user.username
    if m.sender_kind == SupportMessage.SENDER_GUEST:
        return ticket.guest_name or ticket.guest_email or "Гость"
    return ""


def _last_message(ticket: SupportTicket) -> SupportMessage | None:
    return ticket.messages.order_by("-id").select_related("sender_user").first()


@login_required
@member_required
@never_cache
@require_http_methods(["GET"])
def unread_api(request: HttpRequest) -> JsonResponse:
    """Return last unread tickets with metadata for the dropdown."""
    tickets = list(notifications.unread_tickets(request.user)[:10])
    items = []
    for t in tickets:
        items.append({
            "id": t.id,
            "subject": t.subject,
            "author": t.author_label,
            "last_message_at": t.last_message_at.isoformat() if t.last_message_at else None,
            "status": t.status,
            "url": f"/assistant/support/t/{t.id}/",
        })
    return JsonResponse({
        "count": notifications.unread_count(request.user),
        "items": items,
    })


@login_required
@member_required
@never_cache
@require_http_methods(["GET"])
def list_api(request: HttpRequest) -> JsonResponse:
    """All tickets visible to the user, with unread flag + preview + last sender."""
    qs = (
        notifications.visible_tickets(request.user)
        .order_by("-last_message_at", "-created_at")[:50]
    )
    unread_ids = set(notifications.unread_tickets(request.user).values_list("id", flat=True))
    items = []
    for t in qs:
        last = _last_message(t)
        last_kind = last.sender_kind if last else ""
        last_avatar = avatar_url_for_user(last.sender_user) if last and last.sender_user_id else ""
        last_name = _sender_name(last, t) if last else ""
        items.append({
            "id": t.id,
            "subject": t.subject,
            "author": t.author_label,
            "status": t.status,
            "last_message_at": t.last_message_at.isoformat() if t.last_message_at else None,
            "last_body_preview": _preview(last.body) if last else "",
            "last_sender_kind": last_kind,
            "last_sender_avatar_url": last_avatar,
            "last_sender_name": last_name,
            "unread": t.id in unread_ids,
        })
    return JsonResponse({
        "is_admin": _is_admin(request.user),
        "unread_count": notifications.unread_count(request.user),
        "items": items,
    })


@login_required
@member_required
@never_cache
@require_http_methods(["GET"])
def thread_api(request: HttpRequest, ticket_id: int) -> JsonResponse:
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if not _is_admin(request.user) and ticket.author_user_id != request.user.id:
        return JsonResponse({"error": "forbidden"}, status=403)
    notifications.mark_read(request.user, ticket)
    msgs = []
    for m in ticket.messages.order_by("created_at", "id").select_related("sender_user"):
        msgs.append({
            "id": m.id,
            "sender_kind": m.sender_kind,
            "sender_name": _sender_name(m, ticket),
            "sender_avatar_url": avatar_url_for_user(m.sender_user) if m.sender_user_id else "",
            "sender_id": m.sender_user_id or 0,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
        })
    return JsonResponse({
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "author": ticket.author_label,
        "messages": msgs,
        "can_close": _is_admin(request.user),
    })


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def new_api(request: HttpRequest) -> JsonResponse:
    """Create a new ticket from the drawer."""
    if _is_admin(request.user):
        return JsonResponse({"error": "admins_cannot_open"}, status=400)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad_json"}, status=400)
    subject = (body.get("subject") or "").strip()[:200]
    text = (body.get("body") or "").strip()
    if not subject or not text:
        return JsonResponse({"error": "empty"}, status=400)
    if len(text) > 5000:
        return JsonResponse({"error": "too_long"}, status=400)
    ticket = SupportTicket.objects.create(
        author_user=request.user,
        author_kind=SupportTicket.AUTHOR_USER,
        subject=subject,
    )
    SupportMessage.objects.create(
        ticket=ticket,
        sender_kind=SupportMessage.SENDER_USER,
        sender_user=request.user,
        body=text,
    )
    notifications.mark_read(request.user, ticket)
    audit.log(
        action="support_message_sent", actor=request.user, request=request,
        target=ticket, metadata={"ticket_id": ticket.id, "first": True},
    )
    return JsonResponse({"ticket_id": ticket.id})

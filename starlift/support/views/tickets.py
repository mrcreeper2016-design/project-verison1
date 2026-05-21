"""Authenticated support endpoints (drawer-only — no page views)."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from accounts.services import audit

from ..models import SupportTicket, SupportMessage
from ..services import notifications
from ..services.rate_limit import RateLimitExceeded, hit_user
from ..services.typing import set_typing, clear_typing


def _is_admin(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


def _viewer_kind(user) -> str:
    return "admin" if _is_admin(user) else "user"


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def send_message(request: HttpRequest, ticket_id: int) -> JsonResponse:
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    is_admin = _is_admin(request.user)
    if not is_admin and ticket.author_user_id != request.user.id:
        return JsonResponse({"error": "forbidden"}, status=403)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        return JsonResponse({"error": "closed"}, status=400)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad_json"}, status=400)
    content = (body.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "empty"}, status=400)
    if len(content) > 5000:
        return JsonResponse({"error": "too_long"}, status=400)

    try:
        hit_user(request.user)
    except RateLimitExceeded:
        return JsonResponse({"error": "rate_limited"}, status=429)

    sender_kind = SupportMessage.SENDER_ADMIN if is_admin else SupportMessage.SENDER_USER
    msg = SupportMessage.objects.create(
        ticket=ticket,
        sender_kind=sender_kind,
        sender_user=request.user,
        body=content,
    )
    # Sending implicitly clears the user's typing flag.
    clear_typing(ticket.id, _viewer_kind(request.user))
    notifications.mark_read(request.user, ticket)
    audit.log(
        action="support_message_sent",
        actor=request.user,
        request=request,
        target=ticket,
        metadata={"ticket_id": ticket.id, "message_id": msg.id, "kind": sender_kind},
    )

    return JsonResponse({"message_id": msg.id})


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def typing_endpoint(request: HttpRequest, ticket_id: int) -> JsonResponse:
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    is_admin = _is_admin(request.user)
    if not is_admin and ticket.author_user_id != request.user.id:
        return JsonResponse({"error": "forbidden"}, status=403)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        return JsonResponse({"ok": True})
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        body = {}
    kind = _viewer_kind(request.user)
    if body.get("active"):
        set_typing(ticket.id, kind)
    else:
        clear_typing(ticket.id, kind)
    return JsonResponse({"ok": True})


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def close_ticket(request: HttpRequest, ticket_id: int) -> JsonResponse:
    if not _is_admin(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if ticket.status != SupportTicket.STATUS_CLOSED:
        ticket.status = SupportTicket.STATUS_CLOSED
        ticket.closed_at = timezone.now()
        ticket.save(update_fields=["status", "closed_at"])
        SupportMessage.objects.create(
            ticket=ticket, sender_kind=SupportMessage.SENDER_SYSTEM,
            body="Тикет закрыт администратором.",
        )
        audit.log(action="support_ticket_closed", actor=request.user,
                  request=request, target=ticket)
    return JsonResponse({"ok": True})

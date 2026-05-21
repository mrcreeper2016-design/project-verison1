"""Authenticated support: speaker sees own tickets, admin sees all."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from accounts.models import AuditLog
from accounts.services import audit

from ..models import SupportTicket, SupportMessage
from ..services import notifications
from ..services.rate_limit import RateLimitExceeded, hit_user


def _is_admin(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


def _list_tickets_for(user):
    qs = notifications.visible_tickets(user).order_by("-last_message_at", "-created_at")[:50]
    unread_ids = set(notifications.unread_tickets(user).values_list("id", flat=True))
    out = []
    for t in qs:
        out.append({"ticket": t, "unread": t.id in unread_ids})
    return out


@login_required
@member_required
@never_cache
def support_home(request: HttpRequest):
    """Tab view: list + (optionally) selected ticket."""
    tickets = _list_tickets_for(request.user)
    selected = tickets[0]["ticket"] if tickets else None
    if selected:
        return redirect("support:ticket_detail", ticket_id=selected.id)
    return render(request, "support/tab.html", {
        "tickets": tickets,
        "ticket": None,
        "messages_list": [],
        "is_admin": _is_admin(request.user),
        "unread_count": notifications.unread_count(request.user),
    })


@login_required
@member_required
@never_cache
def ticket_detail(request: HttpRequest, ticket_id: int):
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if not _is_admin(request.user) and ticket.author_user_id != request.user.id:
        raise Http404
    notifications.mark_read(request.user, ticket)
    messages_list = list(ticket.messages.order_by("created_at", "id"))
    return render(request, "support/tab.html", {
        "tickets": _list_tickets_for(request.user),
        "ticket": ticket,
        "messages_list": messages_list,
        "is_admin": _is_admin(request.user),
        "unread_count": notifications.unread_count(request.user),
    })


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


@login_required
@member_required
@csrf_protect
@require_http_methods(["GET", "POST"])
def new_ticket(request: HttpRequest):
    """Authenticated user opens a new ticket from the tab."""
    if request.method == "GET":
        return render(request, "support/tab.html", {
            "tickets": _list_tickets_for(request.user),
            "ticket": None,
            "messages_list": [],
            "new_form": True,
            "is_admin": _is_admin(request.user),
            "unread_count": notifications.unread_count(request.user),
        })
    subject = (request.POST.get("subject") or "").strip()[:200]
    body = (request.POST.get("body") or "").strip()
    if not subject or not body:
        return render(request, "support/tab.html", {
            "tickets": _list_tickets_for(request.user),
            "ticket": None,
            "messages_list": [],
            "new_form": True,
            "error": "Заполните тему и сообщение",
            "is_admin": _is_admin(request.user),
            "unread_count": notifications.unread_count(request.user),
        })
    ticket = SupportTicket.objects.create(
        author_user=request.user,
        author_kind=SupportTicket.AUTHOR_USER,
        subject=subject,
    )
    SupportMessage.objects.create(
        ticket=ticket,
        sender_kind=SupportMessage.SENDER_USER,
        sender_user=request.user,
        body=body,
    )
    notifications.mark_read(request.user, ticket)
    audit.log(action="support_message_sent", actor=request.user, request=request,
              target=ticket, metadata={"ticket_id": ticket.id, "first": True})
    return redirect("support:ticket_detail", ticket_id=ticket.id)

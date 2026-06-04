"""Anonymous guest flow: create ticket via magic-link in email."""
from __future__ import annotations

from django.http import HttpRequest, Http404, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from accounts.services import audit

from ..models import SupportTicket, SupportMessage
from ..services.magic_link import make_token, hash_token, verify_token
from ..services.email import send_guest_link
from ..services.rate_limit import RateLimitExceeded, hit_guest
from ..services.typing import set_typing, clear_typing


def _client_ip(request: HttpRequest) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or ""


def _find_ticket_by_token(token: str) -> SupportTicket | None:
    if not token or len(token) < 16:
        return None
    h = hash_token(token)
    return SupportTicket.objects.filter(
        author_kind=SupportTicket.AUTHOR_GUEST, guest_token_hash=h
    ).first()


@never_cache
@require_http_methods(["GET", "POST"])
def guest_new(request: HttpRequest):
    if request.method == "GET":
        return render(request, "support/guest_new.html", {})

    # Honeypot — bots fill hidden fields; humans don't see them.
    if (request.POST.get("website") or "").strip():
        return redirect("/support/new/")

    name = (request.POST.get("name") or "").strip()[:120]
    email = (request.POST.get("email") or "").strip()
    subject = (request.POST.get("subject") or "").strip()[:200]
    body = (request.POST.get("body") or "").strip()
    errors = {}
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Введите корректный email"
    if not subject:
        errors["subject"] = "Укажите тему"
    if not body:
        errors["body"] = "Опишите ваш вопрос"
    if errors:
        return render(request, "support/guest_new.html", {
            "errors": errors, "name": name, "email": email,
            "subject": subject, "body": body,
        })

    try:
        hit_guest(_client_ip(request))
    except RateLimitExceeded:
        return render(request, "support/guest_new.html", {
            "errors": {"rate": "Слишком много обращений. Попробуйте позже."},
            "name": name, "email": email, "subject": subject, "body": body,
        })

    raw_token = make_token()
    ticket = SupportTicket.objects.create(
        author_kind=SupportTicket.AUTHOR_GUEST,
        guest_email=email,
        guest_name=name,
        guest_token_hash=hash_token(raw_token),
        subject=subject,
    )
    SupportMessage.objects.create(
        ticket=ticket, sender_kind=SupportMessage.SENDER_GUEST, body=body,
    )
    try:
        send_guest_link(to=email, raw_token=raw_token, subject_line=subject)
    except Exception:
        pass
    audit.log(action="support_message_sent", request=request, target=ticket,
              metadata={"ticket_id": ticket.id, "guest": True, "first": True})

    from django.conf import settings as _settings
    return render(request, "support/guest_sent.html", {
        "email": email,
        # In DEBUG mode it's handy to display the link inline since console email
        # backend doesn't actually reach the user; production hides it.
        "debug_link": f"/support/t/{raw_token}/" if _settings.DEBUG else "",
    })


@never_cache
def guest_thread(request: HttpRequest, token: str):
    from ..services.avatars import avatar_url_for_user
    import json as _json

    ticket = _find_ticket_by_token(token)
    if ticket is None:
        raise Http404
    messages_list = list(
        ticket.messages.order_by("created_at", "id").select_related("sender_user")
    )

    def _sender_name(m):
        if m.sender_user_id:
            return m.sender_user.get_full_name() or m.sender_user.username
        if m.sender_kind == SupportMessage.SENDER_GUEST:
            return ticket.guest_name or ticket.guest_email or "Гость"
        return ""

    msgs_json = [
        {
            "id": m.id,
            "sender_kind": m.sender_kind,
            "sender_name": _sender_name(m),
            "sender_avatar_url": avatar_url_for_user(m.sender_user) if m.sender_user_id else "",
            "sender_id": m.sender_user_id or 0,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages_list
    ]
    return render(request, "support/guest_thread.html", {
        "ticket": ticket,
        "messages_list": messages_list,
        "messages_data": msgs_json,
        "token": token,
    })


@never_cache
@csrf_protect
@require_http_methods(["POST"])
def guest_send(request: HttpRequest, token: str) -> JsonResponse:
    ticket = _find_ticket_by_token(token)
    if ticket is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        return JsonResponse({"error": "closed"}, status=400)

    import json
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad_json"}, status=400)
    content = (data.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "empty"}, status=400)
    if len(content) > 5000:
        return JsonResponse({"error": "too_long"}, status=400)

    try:
        hit_guest(_client_ip(request))
    except RateLimitExceeded:
        return JsonResponse({"error": "rate_limited"}, status=429)

    msg = SupportMessage.objects.create(
        ticket=ticket, sender_kind=SupportMessage.SENDER_GUEST, body=content,
    )
    clear_typing(ticket.id, "guest")
    audit.log(action="support_message_sent", request=request, target=ticket,
              metadata={"ticket_id": ticket.id, "guest": True, "message_id": msg.id})
    return JsonResponse({"message_id": msg.id})


@never_cache
@csrf_protect
@require_http_methods(["POST"])
def guest_typing(request: HttpRequest, token: str) -> JsonResponse:
    ticket = _find_ticket_by_token(token)
    if ticket is None:
        return JsonResponse({"error": "not_found"}, status=404)
    if ticket.status == SupportTicket.STATUS_CLOSED:
        return JsonResponse({"ok": True})
    import json as _json
    try:
        data = _json.loads(request.body or b"{}")
    except _json.JSONDecodeError:
        data = {}
    if data.get("active"):
        set_typing(ticket.id, "guest")
    else:
        clear_typing(ticket.id, "guest")
    return JsonResponse({"ok": True})

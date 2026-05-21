"""SSE: poll-based, sends new messages + typing events as DB and cache change."""
from __future__ import annotations

import json
import time

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, StreamingHttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache

from accounts.decorators import member_required

from ..models import SupportTicket, SupportMessage
from ..services.avatars import avatar_url_for_user
from ..services.magic_link import hash_token
from ..services.typing import get_active_kinds


POLL_INTERVAL = 1.0
MAX_DURATION = 60.0  # 1-minute cap; client reconnects automatically


def _format(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _viewer_kind(user, ticket: SupportTicket, is_guest: bool) -> str:
    if is_guest:
        return "guest"
    if user.is_superuser:
        return "admin"
    profile = getattr(user, "profile", None)
    if profile and profile.role == "admin":
        return "admin"
    return "user"


def _sender_name(m: SupportMessage, ticket: SupportTicket) -> str:
    if m.sender_user_id:
        return m.sender_user.get_full_name() or m.sender_user.username
    if m.sender_kind == SupportMessage.SENDER_GUEST:
        return ticket.guest_name or ticket.guest_email or "Гость"
    return ""


def _stream(ticket: SupportTicket, viewer_kind: str):
    last_id = (
        ticket.messages.order_by("-id").values_list("id", flat=True).first() or 0
    )
    started = time.time()
    yield ":hb\n\n"  # Initial heartbeat — confirms `open` for the client.

    # Track "other party typing" set so we only emit on change.
    prev_typing_others: set[str] = set()

    while time.time() - started < MAX_DURATION:
        time.sleep(POLL_INTERVAL)

        new_qs = (
            SupportMessage.objects
            .filter(ticket=ticket, id__gt=last_id)
            .order_by("id")
            .select_related("sender_user")
        )
        for m in new_qs:
            payload = {
                "id": m.id,
                "sender_kind": m.sender_kind,
                "sender_name": _sender_name(m, ticket),
                "sender_avatar_url": (
                    avatar_url_for_user(m.sender_user) if m.sender_user_id else ""
                ),
                "sender_id": m.sender_user_id or 0,
                "body": m.body,
                "created_at": m.created_at.isoformat(),
            }
            yield _format("message", payload)
            last_id = m.id

        # Typing: emit only state changes, only for "other" parties.
        active = get_active_kinds(ticket.id) - {viewer_kind}
        if active != prev_typing_others:
            added = active - prev_typing_others
            removed = prev_typing_others - active
            for k in added:
                yield _format("typing", {"kind": k, "active": True})
            for k in removed:
                yield _format("typing", {"kind": k, "active": False})
            prev_typing_others = active

        # Re-fetch status; close event when admin closes ticket.
        st = SupportTicket.objects.only("status").get(pk=ticket.pk)
        if st.status == SupportTicket.STATUS_CLOSED:
            yield _format("status", {"status": "closed"})
            return
        yield ":hb\n\n"


def _is_admin(user) -> bool:
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


@login_required
@member_required
@never_cache
def user_stream(request: HttpRequest, ticket_id: int) -> StreamingHttpResponse:
    ticket = get_object_or_404(SupportTicket, pk=ticket_id)
    if not _is_admin(request.user) and ticket.author_user_id != request.user.id:
        raise Http404
    viewer_kind = _viewer_kind(request.user, ticket, is_guest=False)
    resp = StreamingHttpResponse(_stream(ticket, viewer_kind), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@never_cache
def guest_stream(request: HttpRequest, token: str) -> StreamingHttpResponse:
    h = hash_token(token)
    ticket = SupportTicket.objects.filter(
        author_kind=SupportTicket.AUTHOR_GUEST, guest_token_hash=h
    ).first()
    if ticket is None:
        raise Http404
    resp = StreamingHttpResponse(_stream(ticket, "guest"), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp

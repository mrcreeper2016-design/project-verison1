"""SSE: poll-based, sends new messages as they appear in the DB."""
from __future__ import annotations

import json
import time

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, StreamingHttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache

from accounts.decorators import member_required

from ..models import SupportTicket, SupportMessage
from ..services.magic_link import hash_token


POLL_INTERVAL = 1.0
MAX_DURATION = 60.0  # 1-minute cap; client reconnects automatically


def _format(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream(ticket: SupportTicket):
    last_id = (
        ticket.messages.order_by("-id").values_list("id", flat=True).first() or 0
    )
    started = time.time()
    # Heartbeat once to confirm connection is live.
    yield ":hb\n\n"
    while time.time() - started < MAX_DURATION:
        time.sleep(POLL_INTERVAL)
        new_qs = SupportMessage.objects.filter(ticket=ticket, id__gt=last_id).order_by("id")
        for m in new_qs:
            payload = {
                "id": m.id,
                "sender_kind": m.sender_kind,
                "sender_name": (
                    m.sender_user.get_full_name() or m.sender_user.username
                    if m.sender_user_id else ""
                ),
                "body": m.body,
                "created_at": m.created_at.isoformat(),
            }
            yield _format("message", payload)
            last_id = m.id
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
    resp = StreamingHttpResponse(_stream(ticket), content_type="text/event-stream")
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
    resp = StreamingHttpResponse(_stream(ticket), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp

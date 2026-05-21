"""One-conversation-per-user model.

The assistant lives as a floating widget (FAB drawer) on every page, so we
keep exactly one active conversation per user. ``state`` returns it (creating
on demand) with its current messages. ``clear`` wipes the conversation so the
next ``state`` call returns a fresh one.
"""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from assistant.models import Conversation, Message


def _get_or_create_single(user) -> Conversation:
    conv = (
        Conversation.objects.filter(user=user, archived_at__isnull=True)
        .order_by("-updated_at")
        .first()
    )
    if conv is None:
        conv = Conversation.objects.create(user=user)
    return conv


def _message_to_dict(m: Message) -> dict:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content or "",
        "tool_name": m.tool_name or "",
        "created_at": m.created_at.isoformat(),
    }


@login_required
@member_required
@never_cache
@require_http_methods(["GET"])
def state(request: HttpRequest) -> JsonResponse:
    """Return the user's single conversation with all messages.

    The FAB drawer calls this on first open to hydrate its thread.
    """
    conv = _get_or_create_single(request.user)
    msgs = list(conv.messages.order_by("created_at", "id"))
    return JsonResponse({
        "conversation_id": conv.id,
        "messages": [_message_to_dict(m) for m in msgs],
    })


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def clear(request: HttpRequest) -> JsonResponse:
    """Wipe the user's single conversation. Next ``state`` creates a new one."""
    Conversation.objects.filter(user=request.user).delete()
    new_conv = Conversation.objects.create(user=request.user)
    return JsonResponse({"conversation_id": new_conv.id})


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def create_conversation(request: HttpRequest) -> JsonResponse:
    """Legacy endpoint kept for compatibility.

    With the single-conversation model we never actually create a parallel
    one — return the existing conversation (or one created on the fly),
    seeded with the first user message if provided.
    """
    body = json.loads(request.body or b"{}")
    first_message = (body.get("first_message") or "").strip()
    conv = _get_or_create_single(request.user)
    if first_message:
        Message.objects.create(conversation=conv, role=Message.ROLE_USER, content=first_message)
    return JsonResponse({"conversation_id": conv.id})

"""Create/list/archive conversations."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from assistant.models import Conversation, Message


@login_required
@member_required
@never_cache
@require_http_methods(["GET"])
def chat_home(request: HttpRequest) -> HttpResponse:
    """Open the most-recent conversation, or create a fresh one."""
    conv = (
        Conversation.objects.filter(user=request.user, archived_at__isnull=True)
        .order_by("-updated_at")
        .first()
    )
    if conv:
        return redirect("assistant:chat_detail", conversation_id=conv.id)
    conv = Conversation.objects.create(user=request.user)
    return redirect("assistant:chat_detail", conversation_id=conv.id)


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def create_conversation(request: HttpRequest) -> JsonResponse:
    body = json.loads(request.body or b"{}")
    first_message = (body.get("first_message") or "").strip()
    conv = Conversation.objects.create(user=request.user, title=first_message[:120])
    if first_message:
        Message.objects.create(conversation=conv, role=Message.ROLE_USER, content=first_message)
    return JsonResponse({"conversation_id": conv.id})


@login_required
@member_required
@require_http_methods(["GET"])
def list_conversations(request: HttpRequest) -> JsonResponse:
    convs = (
        Conversation.objects.filter(user=request.user, archived_at__isnull=True)
        .order_by("-updated_at")[:20]
    )
    return JsonResponse({
        "conversations": [
            {
                "id": c.id,
                "title": c.title or "Без названия",
                "updated_at": c.updated_at.isoformat(),
            }
            for c in convs
        ]
    })

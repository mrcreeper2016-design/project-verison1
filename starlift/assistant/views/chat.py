"""Chat detail page + SSE stream + send-message endpoint."""
from __future__ import annotations

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required
from accounts.models import AuditLog
from accounts.services import audit
from assistant.agent.gigachat_client import GigaChatClient
from assistant.agent.loop import run_turn
from assistant.models import Conversation, Message
from assistant.services.rate_limit import RateLimitExceeded, hit


def _own_conv(request: HttpRequest, conversation_id: int) -> Conversation:
    return get_object_or_404(Conversation, id=conversation_id, user=request.user)


@login_required
@member_required
@never_cache
def chat_detail(request: HttpRequest, conversation_id: int):
    conv = _own_conv(request, conversation_id)
    messages = list(conv.messages.order_by("created_at", "id"))
    sidebar = (
        Conversation.objects.filter(user=request.user, archived_at__isnull=True)
        .order_by("-updated_at")[:20]
    )
    return render(request, "assistant/chat.html", {
        "conversation": conv,
        "messages": messages,
        "conversations_sidebar": sidebar,
        "assistant_enabled": settings.ASSISTANT_ENABLED,
    })


@login_required
@member_required
@csrf_protect
@require_http_methods(["POST"])
def send_message(request: HttpRequest, conversation_id: int) -> JsonResponse:
    conv = _own_conv(request, conversation_id)
    body = json.loads(request.body or b"{}")
    content = (body.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "empty"}, status=400)
    try:
        hit(request.user)
    except RateLimitExceeded:
        return JsonResponse({"error": "rate_limited"}, status=429)
    msg = Message.objects.create(conversation=conv, role=Message.ROLE_USER, content=content)
    audit.log(
        action=AuditLog.ACTION_ASSISTANT_QUERY,
        actor=request.user,
        request=request,
        target=request.user,
        metadata={"conversation_id": conv.id, "message_id": msg.id},
    )
    return JsonResponse({"message_id": msg.id})


@login_required
@member_required
@never_cache
def stream(request: HttpRequest, conversation_id: int) -> StreamingHttpResponse:
    conv = _own_conv(request, conversation_id)

    def _generate():
        client = GigaChatClient()
        for event in run_turn(conv, client=client):
            payload = json.dumps(event.payload, ensure_ascii=False)
            yield f"event: {event.kind}\ndata: {payload}\n\n"

    response = StreamingHttpResponse(_generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response

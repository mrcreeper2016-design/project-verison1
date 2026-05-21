"""JSON API for the header bell."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from accounts.decorators import member_required

from ..services import notifications


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

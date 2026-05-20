"""Single point of entry for writing audit-log records.

Keeping all audit writes here makes it easy to later swap storage, add
async fan-out (e.g. a SIEM), or redact sensitive fields in one place.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from django.contrib.auth import get_user_model
from django.http import HttpRequest

from ..models import AuditLog


MAX_UA_LENGTH = 500


def _client_ip(request: Optional[HttpRequest]) -> Optional[str]:
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def _user_agent(request: Optional[HttpRequest]) -> str:
    if request is None:
        return ""
    return (request.META.get("HTTP_USER_AGENT") or "")[:MAX_UA_LENGTH]


def log(
    *,
    action: str,
    actor=None,
    request: Optional[HttpRequest] = None,
    target: Any = None,
    target_type: str = "",
    target_id: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> AuditLog:
    """Record an auditable event.

    - `actor` may be a User instance, an AnonymousUser, or None.
    - If `target` is passed, `target_type` and `target_id` are derived
      from it (overrides explicit values for consistency).
    """
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None

    if target is not None:
        target_type = target_type or target.__class__.__name__
        target_id = target_id or str(getattr(target, "pk", ""))

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=(target_type or "")[:64],
        target_id=(target_id or "")[:64],
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        metadata=dict(metadata or {}),
    )

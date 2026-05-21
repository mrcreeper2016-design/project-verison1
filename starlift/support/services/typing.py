"""Presence-style "X is typing…" via Django cache (short TTL).

Key format: support:typing:<ticket_id>:<sender_kind>
Sender kinds: "user", "admin", "guest".
"""
from __future__ import annotations

from django.core.cache import cache

TTL = 4  # seconds — heartbeats from client come every ~2s


def _key(ticket_id: int, kind: str) -> str:
    return f"support:typing:{ticket_id}:{kind}"


def set_typing(ticket_id: int, kind: str) -> None:
    cache.set(_key(ticket_id, kind), 1, timeout=TTL)


def clear_typing(ticket_id: int, kind: str) -> None:
    cache.delete(_key(ticket_id, kind))


def get_active_kinds(ticket_id: int) -> set[str]:
    out = set()
    for k in ("user", "admin", "guest"):
        if cache.get(_key(ticket_id, k)):
            out.add(k)
    return out

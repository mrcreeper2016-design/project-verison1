"""Sliding-window rate limit for support endpoints.

Uses Django cache like ``assistant.services.rate_limit`` but with its own
namespace and separate user/guest tunables.
"""
from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache


class RateLimitExceeded(Exception):
    pass


def _hit(key: str, limit: int, window: int) -> None:
    now = int(time.time())
    timestamps = cache.get(key) or []
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= limit:
        raise RateLimitExceeded()
    timestamps.append(now)
    cache.set(key, timestamps, timeout=window)


def hit_user(user) -> None:
    limit = getattr(settings, "SUPPORT_RATE_LIMIT_PER_USER", 30)
    window = getattr(settings, "SUPPORT_RATE_LIMIT_WINDOW_SECONDS", 300)
    _hit(f"support:rl:u:{user.id}", limit, window)


def hit_guest(ip: str) -> None:
    limit = getattr(settings, "SUPPORT_RATE_LIMIT_PER_GUEST", 5)
    window = getattr(settings, "SUPPORT_RATE_LIMIT_WINDOW_SECONDS", 300)
    _hit(f"support:rl:g:{ip or 'unknown'}", limit, window)

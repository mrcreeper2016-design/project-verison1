"""Per-user assistant rate limit using Django cache."""
from __future__ import annotations

import time

from django.conf import settings
from django.core.cache import cache


class RateLimitExceeded(Exception):
    pass


def _key(user_id: int) -> str:
    return f"assistant:rl:{user_id}"


def hit(user) -> None:
    """Record one message; raise ``RateLimitExceeded`` if over the limit."""
    window = settings.ASSISTANT_RATE_LIMIT_WINDOW_SECONDS
    limit = settings.ASSISTANT_RATE_LIMIT_PER_USER
    now = int(time.time())
    key = _key(user.id)
    timestamps = cache.get(key) or []
    timestamps = [t for t in timestamps if now - t < window]
    if len(timestamps) >= limit:
        raise RateLimitExceeded()
    timestamps.append(now)
    cache.set(key, timestamps, timeout=window)

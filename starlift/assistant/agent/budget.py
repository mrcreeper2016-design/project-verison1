"""Token-budget enforcement.

Three checked tiers: per-conversation total, per-user daily, and a global
daily kill-switch. Per-turn limits live in the agent loop itself.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from accounts.models import UserProfile
from assistant.models import Conversation, Message


class BudgetExceeded(Exception):
    """Raised when one of the token budgets is hit."""

    def __init__(self, *, scope: str, used: int, limit: int):
        super().__init__(f"Budget exceeded ({scope}): {used}/{limit}")
        self.scope = scope
        self.used = used
        self.limit = limit


def _conversation_total(conv: Conversation) -> int:
    agg = conv.messages.aggregate(t_in=Sum("token_in"), t_out=Sum("token_out"))
    return (agg["t_in"] or 0) + (agg["t_out"] or 0)


def check_conversation_budget(conv: Conversation) -> None:
    limit = settings.ASSISTANT_MAX_TOKENS_PER_CONVERSATION
    used = _conversation_total(conv)
    if used >= limit:
        raise BudgetExceeded(scope="conversation", used=used, limit=limit)


def sum_user_tokens_24h(user) -> int:
    since = timezone.now() - timedelta(hours=24)
    agg = Message.objects.filter(
        conversation__user=user,
        created_at__gte=since,
    ).aggregate(t_in=Sum("token_in"), t_out=Sum("token_out"))
    return (agg["t_in"] or 0) + (agg["t_out"] or 0)


def _daily_limit_for(user) -> int:
    try:
        role = user.profile.role
    except (UserProfile.DoesNotExist, AttributeError):
        role = UserProfile.ROLE_GUEST
    if role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_DEVREL):
        return settings.ASSISTANT_DAILY_TOKEN_BUDGET_ADMIN
    return settings.ASSISTANT_DAILY_TOKEN_BUDGET_SPEAKER


def check_daily_budget(user) -> None:
    limit = _daily_limit_for(user)
    used = sum_user_tokens_24h(user)
    if used >= limit and settings.ASSISTANT_DAILY_BUDGET_ACTION == "block":
        raise BudgetExceeded(scope="daily", used=used, limit=limit)


def check_global_budget() -> None:
    since = timezone.now() - timedelta(hours=24)
    agg = Message.objects.filter(created_at__gte=since).aggregate(
        t_in=Sum("token_in"), t_out=Sum("token_out")
    )
    used = (agg["t_in"] or 0) + (agg["t_out"] or 0)
    limit = settings.ASSISTANT_DAILY_GLOBAL_BUDGET
    if used >= limit:
        raise BudgetExceeded(scope="global", used=used, limit=limit)

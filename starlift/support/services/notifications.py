"""Unread-counter helpers for the header bell badge."""
from __future__ import annotations

from typing import Iterable

from django.db.models import Q

from ..models import SupportTicket, SupportRead


def _is_admin(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == "admin")


def visible_tickets(user) -> "models.QuerySet[SupportTicket]":
    """Tickets the user is allowed to see — admins: all, speakers: own."""
    if _is_admin(user):
        return SupportTicket.objects.all()
    return SupportTicket.objects.filter(author_user=user)


def unread_tickets(user) -> "models.QuerySet[SupportTicket]":
    """Tickets with an unread message addressed to this user.

    For admins: tickets where last message is NOT from an admin and the
    admin hasn't read past ``last_message_at``.
    For speakers (ticket authors): tickets where last message is NOT from
    them (i.e. an admin reply) and they haven't read it yet.
    """
    qs = visible_tickets(user).exclude(last_message_at__isnull=True)
    if _is_admin(user):
        # admin's unread = last message from user or guest (i.e. needs a reply)
        qs = qs.filter(last_message_sender_kind__in=("user", "guest"))
    else:
        # author user's unread = last message from admin or system
        qs = qs.filter(last_message_sender_kind__in=("admin", "system"))

    read_map = {
        r.ticket_id: r.last_read_at
        for r in SupportRead.objects.filter(user=user, ticket__in=qs)
    }
    ids = [t.id for t in qs if read_map.get(t.id) is None or t.last_message_at > read_map[t.id]]
    return SupportTicket.objects.filter(id__in=ids).order_by("-last_message_at")


def unread_count(user) -> int:
    if not getattr(user, "is_authenticated", False):
        return 0
    return unread_tickets(user).count()


def mark_read(user, ticket: SupportTicket) -> None:
    from django.utils import timezone

    if not getattr(user, "is_authenticated", False):
        return
    SupportRead.objects.update_or_create(
        ticket=ticket, user=user, defaults={"last_read_at": timezone.now()}
    )

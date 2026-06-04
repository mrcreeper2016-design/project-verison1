"""Models for the support chat: tickets, messages, per-user read markers."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class SupportTicket(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [(STATUS_OPEN, "open"), (STATUS_CLOSED, "closed")]

    AUTHOR_USER = "user"
    AUTHOR_GUEST = "guest"
    AUTHOR_KIND_CHOICES = [(AUTHOR_USER, "user"), (AUTHOR_GUEST, "guest")]

    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="support_tickets",
    )
    author_kind = models.CharField(max_length=8, choices=AUTHOR_KIND_CHOICES)
    guest_email = models.EmailField(blank=True, default="")
    guest_name = models.CharField(max_length=120, blank=True, default="")
    guest_token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    guest_notified_at = models.DateTimeField(null=True, blank=True)

    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_sender_kind = models.CharField(max_length=8, blank=True, default="")

    class Meta:
        db_table = "support_ticket"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-last_message_at"]),
            models.Index(fields=["author_user", "-last_message_at"]),
        ]

    def __str__(self) -> str:
        return f"Ticket<{self.id}: {self.subject[:30]}>"

    @property
    def author_label(self) -> str:
        if self.author_kind == self.AUTHOR_GUEST:
            name = self.guest_name or self.guest_email or "Гость"
            return f"Гость · {name}"
        if self.author_user_id:
            u = self.author_user
            return u.get_full_name() or u.username
        return "—"


class SupportMessage(models.Model):
    SENDER_USER = "user"
    SENDER_ADMIN = "admin"
    SENDER_GUEST = "guest"
    SENDER_SYSTEM = "system"
    SENDER_CHOICES = [
        (SENDER_USER, "user"),
        (SENDER_ADMIN, "admin"),
        (SENDER_GUEST, "guest"),
        (SENDER_SYSTEM, "system"),
    ]

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    sender_kind = models.CharField(max_length=8, choices=SENDER_CHOICES)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "support_message"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["ticket", "created_at"])]

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            SupportTicket.objects.filter(pk=self.ticket_id).update(
                last_message_at=self.created_at or timezone.now(),
                last_message_sender_kind=self.sender_kind,
                updated_at=timezone.now(),
            )


class SupportRead(models.Model):
    """When a user (admin or author) last read a given ticket.

    Used to compute the unread count for the header bell without scanning
    every message — we only compare ``ticket.last_message_at`` against
    ``last_read_at`` and the kind of the last sender.
    """

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    last_read_at = models.DateTimeField()

    class Meta:
        db_table = "support_read"
        unique_together = [("ticket", "user")]
        indexes = [models.Index(fields=["user", "ticket"])]

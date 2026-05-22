import uuid

from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_DEVREL = "devrel"
    ROLE_SPEAKER = "speaker"
    ROLE_GUEST = "guest"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Администратор"),
        (ROLE_DEVREL, "DevRel"),
        (ROLE_SPEAKER, "Спикер"),
        (ROLE_GUEST, "Гость"),
    ]
    STAFF_ROLES = (ROLE_ADMIN, ROLE_DEVREL)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=True,
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_SPEAKER)
    company = models.CharField(max_length=200, blank=True, default="")
    email_verified = models.BooleanField(default=False)
    pending_email = models.EmailField(null=True, blank=True)
    bio = models.TextField(blank=True, default="")
    avatar = models.ImageField(upload_to="avatars/users/", null=True, blank=True)
    pdn_consent_at = models.DateTimeField(null=True, blank=True)
    policy_accepted_at = models.DateTimeField(null=True, blank=True)
    consent_doc_version = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_userprofile"
        verbose_name = "Профиль пользователя"
        verbose_name_plural = "Профили пользователей"

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_devrel(self) -> bool:
        return self.role == self.ROLE_DEVREL

    @property
    def is_staff_member(self) -> bool:
        """admin or devrel — full content management privileges."""
        return self.role in self.STAFF_ROLES

    @property
    def is_speaker(self) -> bool:
        return self.role == self.ROLE_SPEAKER

    @property
    def is_guest(self) -> bool:
        return self.role == self.ROLE_GUEST

    @property
    def is_member(self) -> bool:
        """Member == anyone but guest (admin, devrel, speaker)."""
        return self.role in (self.ROLE_ADMIN, self.ROLE_DEVREL, self.ROLE_SPEAKER)

    @property
    def avatar_url(self) -> str:
        if self.avatar:
            try:
                return self.avatar.url
            except ValueError:
                return ""
        return ""


class Invite(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=UserProfile.ROLE_CHOICES, default=UserProfile.ROLE_SPEAKER)
    speaker = models.ForeignKey(
        "starlift.Speaker",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invites",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_created",
    )
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consumed_invite",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_invite"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Invite<{self.email} / {self.role}>"

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        from django.utils import timezone
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        return not (self.is_used or self.is_revoked or self.is_expired)


class EmailVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verifications",
    )
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_email_verification"
        ordering = ["-created_at"]


class LoginAttempt(models.Model):
    username_or_email = models.CharField(max_length=254, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "accounts_login_attempt"
        indexes = [models.Index(fields=["username_or_email", "created_at", "success"])]
        ordering = ["-created_at"]

    def __str__(self):
        flag = "ok" if self.success else "fail"
        return f"{self.username_or_email} [{flag}] @ {self.created_at:%Y-%m-%d %H:%M:%S}"


class AuditLog(models.Model):
    ACTION_LOGIN_SUCCESS = "login_success"
    ACTION_LOGIN_FAILED = "login_failed"
    ACTION_LOGOUT = "logout"
    ACTION_LOCKOUT_TRIGGERED = "lockout_triggered"
    ACTION_LOCKOUT_LIFTED = "lockout_lifted"
    ACTION_PASSWORD_CHANGED = "password_changed"
    ACTION_PASSWORD_RESET_REQUESTED = "password_reset_requested"
    ACTION_PASSWORD_RESET_COMPLETED = "password_reset_completed"
    ACTION_EMAIL_CHANGE_REQUESTED = "email_change_requested"
    ACTION_EMAIL_CHANGE_CONFIRMED = "email_change_confirmed"
    ACTION_PROFILE_UPDATED = "profile_updated"
    ACTION_INVITE_CREATED = "invite_created"
    ACTION_INVITE_REVOKED = "invite_revoked"
    ACTION_INVITE_CONSUMED = "invite_consumed"
    ACTION_ROLE_CHANGED = "role_changed"
    ACTION_USER_DEACTIVATED = "user_deactivated"
    ACTION_USER_ACTIVATED = "user_activated"
    ACTION_SPEAKER_LINKED = "speaker_linked"
    ACTION_SPEAKER_UNLINKED = "speaker_unlinked"
    ACTION_GUEST_REGISTERED = "guest_registered"
    ACTION_GUEST_PROMOTED = "guest_promoted"
    ACTION_GUEST_DELETED = "guest_deleted"
    ACTION_EMAIL_VERIFIED = "email_verified"
    ACTION_CONSENT_GIVEN = "consent_given"
    ACTION_ASSISTANT_QUERY = "assistant_query"
    ACTION_SPEAKER_APPLICATION_SUBMITTED = "speaker_application_submitted"
    ACTION_SPEAKER_APPLICATION_APPROVED = "speaker_application_approved"
    ACTION_SPEAKER_APPLICATION_REJECTED = "speaker_application_rejected"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "accounts_audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def __str__(self):
        actor = self.actor.username if self.actor else "-"
        return f"[{self.created_at:%Y-%m-%d %H:%M:%S}] {actor} / {self.action}"

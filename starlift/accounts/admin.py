from django.contrib import admin

from .models import AuditLog, EmailVerification, Invite, LoginAttempt, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "email_verified", "updated_at")
    list_filter = ("role", "email_verified")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("email", "role", "speaker", "created_by", "expires_at", "used_at", "revoked_at", "created_at")
    list_filter = ("role", "used_at", "revoked_at")
    search_fields = ("email", "created_by__username", "consumed_by__username")
    readonly_fields = ("id", "token_hash", "created_at", "used_at", "consumed_by", "revoked_at")
    autocomplete_fields = ("speaker", "created_by", "consumed_by")


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "new_email", "expires_at", "used_at", "created_at")
    search_fields = ("user__username", "new_email")
    readonly_fields = ("id", "token_hash", "created_at", "used_at")


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("username_or_email", "ip", "success", "created_at")
    list_filter = ("success",)
    search_fields = ("username_or_email", "ip")
    readonly_fields = ("username_or_email", "ip", "success", "created_at")

    def has_add_permission(self, request):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_type", "target_id", "ip")
    list_filter = ("action",)
    search_fields = ("actor__username", "target_id", "ip")
    readonly_fields = (
        "actor",
        "action",
        "target_type",
        "target_id",
        "ip",
        "user_agent",
        "metadata",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

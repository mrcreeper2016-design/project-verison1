from django.contrib import admin

from .models import SupportTicket, SupportMessage, SupportRead


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    readonly_fields = ("created_at",)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "status", "author_kind", "author_label", "last_message_at", "created_at")
    list_filter = ("status", "author_kind")
    search_fields = ("subject", "guest_email", "guest_name", "author_user__username", "author_user__email")
    inlines = [SupportMessageInline]
    readonly_fields = ("guest_token_hash", "last_message_at", "last_message_sender_kind", "created_at", "updated_at", "closed_at")


@admin.register(SupportRead)
class SupportReadAdmin(admin.ModelAdmin):
    list_display = ("user", "ticket", "last_read_at")

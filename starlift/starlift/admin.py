from django.contrib import admin

from .models import Event, Feedback, Speaker


@admin.register(Speaker)
class SpeakerAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "link_status_display", "nps", "recommended", "created_at")
    list_filter = ("status", "recommended", "city")
    search_fields = ("name", "sub", "stack", "city")
    readonly_fields = ("nps", "status", "created_at")

    @admin.display(description="Статус", ordering="status")
    def link_status_display(self, obj: Speaker) -> str:
        return obj.link_status_display


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "event_date", "source", "is_external", "created_at")
    list_filter = ("status", "source", "is_external")
    search_fields = ("title", "location", "topic")
    filter_horizontal = ("speakers",)
    readonly_fields = ("created_at",)


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("speaker", "event", "score", "created_at", "ip_address")
    list_filter = ("score",)
    search_fields = ("speaker__name", "event__title", "ip_address")
    readonly_fields = ("created_at",)

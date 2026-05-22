from django.urls import path

from .views import tickets, stream, api

# Support is drawer-only — no page-level entry point. These are only
# backend endpoints called by the FAB drawer JS.
urlpatterns = [
    path("t/<int:ticket_id>/send/", tickets.send_message, name="send_message"),
    path("t/<int:ticket_id>/typing/", tickets.typing_endpoint, name="typing"),
    path("t/<int:ticket_id>/stream/", stream.user_stream, name="ticket_stream"),
    path("t/<int:ticket_id>/close/", tickets.close_ticket, name="close_ticket"),
    path("t/<int:ticket_id>/delete/", tickets.delete_ticket, name="delete_ticket"),

    # JSON API consumed by the drawer pane
    path("api/unread/", api.unread_api, name="api_unread"),
    path("api/list/", api.list_api, name="api_list"),
    path("api/t/<int:ticket_id>/", api.thread_api, name="api_thread"),
    path("api/new/", api.new_api, name="api_new"),
]

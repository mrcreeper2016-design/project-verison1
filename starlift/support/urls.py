from django.urls import path

from .views import tickets, stream, api

urlpatterns = [
    # Authenticated tab inside the assistant page
    path("", tickets.support_home, name="home"),
    path("t/<int:ticket_id>/", tickets.ticket_detail, name="ticket_detail"),
    path("t/<int:ticket_id>/send/", tickets.send_message, name="send_message"),
    path("t/<int:ticket_id>/stream/", stream.user_stream, name="ticket_stream"),
    path("t/<int:ticket_id>/close/", tickets.close_ticket, name="close_ticket"),
    path("new/", tickets.new_ticket, name="new_ticket"),

    # API
    path("api/unread/", api.unread_api, name="api_unread"),
]

from django.urls import path

from .views import chat, conversations

app_name = "assistant"

# Assistant is drawer-only — no page-level routes. Backend endpoints below
# are consumed by the FAB drawer widget in templates/base.html.
urlpatterns = [
    path("state/", conversations.state, name="state"),
    path("clear/", conversations.clear, name="clear"),
    path("conversations/", conversations.create_conversation, name="conversations_create"),
    path("c/<int:conversation_id>/send/", chat.send_message, name="chat_send"),
    path("c/<int:conversation_id>/stream/", chat.stream, name="chat_stream"),
]

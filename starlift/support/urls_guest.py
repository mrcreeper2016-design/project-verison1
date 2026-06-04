from django.urls import path

from .views import guest, stream

urlpatterns = [
    path("new/", guest.guest_new, name="guest_new"),
    path("t/<str:token>/", guest.guest_thread, name="guest_thread"),
    path("t/<str:token>/send/", guest.guest_send, name="guest_send"),
    path("t/<str:token>/typing/", guest.guest_typing, name="guest_typing"),
    path("t/<str:token>/stream/", stream.guest_stream, name="guest_stream"),
]

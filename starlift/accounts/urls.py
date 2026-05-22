from django.urls import path

from .views import auth as auth_views
from .views import console as console_views
from .views import email as email_views
from .views import invite as invite_views
from .views import password as pwd_views
from .views import profile as profile_views
from .views import register as register_views
from .views import speaker_application as application_views

app_name = "accounts"

urlpatterns = [
    path("auth/login/", auth_views.login_view, name="login"),
    path("auth/logout/", auth_views.logout_view, name="logout"),

    path("auth/register/", register_views.register_view, name="register"),
    path("auth/register/pending/", register_views.register_pending_view, name="register_pending"),

    path("auth/password-reset/", pwd_views.StarliftPasswordResetView.as_view(), name="password_reset"),
    path("auth/password-reset/done/", pwd_views.StarliftPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("auth/reset/<uidb64>/<token>/", pwd_views.StarliftPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("auth/reset/done/", pwd_views.StarliftPasswordResetCompleteView.as_view(), name="password_reset_complete"),

    path("auth/password-change/", pwd_views.StarliftPasswordChangeView.as_view(), name="password_change"),
    path("auth/password-change/done/", pwd_views.StarliftPasswordChangeDoneView.as_view(), name="password_change_done"),

    path("auth/email/verify/<str:token>/", email_views.verify_email_view, name="verify_email"),

    path("auth/invite/<str:token>/", invite_views.invite_accept_view, name="invite_accept"),

    path("profile/", profile_views.profile_view, name="profile"),
    path("profile/email/", profile_views.email_change_view, name="email_change"),
    path("profile/email/cancel/", profile_views.email_change_cancel_view, name="email_change_cancel"),

    path("console/", console_views.users_view, name="console_home"),
    path("console/users/", console_views.users_view, name="users"),
    path("console/users/<int:user_id>/", console_views.user_detail_view, name="user_detail"),
    path("console/invites/", invite_views.invites_view, name="invites"),
    path("console/invites/<uuid:invite_id>/revoke/", invite_views.invite_revoke_view, name="invite_revoke"),
    path("console/audit/", console_views.audit_view, name="audit"),
    path("console/event-requests/", console_views.event_requests_view, name="event_requests"),
    path("console/event-requests/<int:request_id>/<str:action>/", console_views.event_request_action_view, name="event_request_action"),

    path("console/events/<int:event_id>/invite/", console_views.event_invite_view, name="event_invite"),
    path("console/event-invitations/<int:invitation_id>/cancel/", console_views.event_invitation_cancel_view, name="event_invitation_cancel"),

    path("console/speaker-applications/<int:application_id>/", console_views.speaker_application_detail_view, name="speaker_application_detail"),
    path("console/speaker-applications/<int:application_id>/<str:action>/", console_views.speaker_application_action_view, name="speaker_application_action"),

    path("application/", application_views.speaker_application_form_view, name="speaker_application_form"),
    path("application/pending/", application_views.application_pending_view, name="speaker_application_pending"),
]

from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as static_serve
from starlift import views, views_me

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('me/', views_me.dashboard_view, name='me_dashboard'),
    path('me/feedback/', views_me.feedback_view, name='me_feedback'),
    path('me/feedback/export.csv', views_me.feedback_csv_export, name='me_feedback_csv'),
    path('me/events/', views_me.events_view, name='me_events'),
    path('me/events/<int:event_id>/rate/', views_me.rate_event_view, name='me_event_rate'),
    path('me/requests/', views_me.requests_view, name='me_requests'),
    path('me/favorites/', views_me.favorites_view, name='me_favorites'),
    path('', views.index_view, name='home'),
    path('index/', views.index_view, name='index'),
    path('explore/', views.explore_view, name='explore'),
    path('speakers/', views.speakers_view, name='speakers'),
    path('events/', views.events_view, name='events'),
    path('analytics/', views.analytics_view, name='analytics'),
    path('api/speakers/', views.speakers_api, name='speakers_api'),
    path('api/speakers/<int:speaker_id>/like/', views.speaker_like_toggle, name='speaker_like_toggle'),
    path('api/speakers/<int:speaker_id>/recommend/', views.speaker_recommend_toggle, name='speaker_recommend_toggle'),
    path('api/events/', views.events_api, name='events_api'),
    path('api/home/', views.home_api, name='home_api'),
    path('speakers/add/', views.speaker_add, name='speaker_add'),
    path('speakers/edit/<int:pk>/', views.speaker_edit, name='speaker_edit'),
    path('speakers/delete/<int:pk>/', views.speaker_delete, name='speaker_delete'),
    path('speaker/<int:speaker_id>/event/<int:event_id>/qr/', views.generate_qr_view, name='generate_qr'),
    path('speaker/<int:speaker_id>/event/<int:event_id>/qr/poster.png', views.qr_poster_view, name='qr_poster'),
    path('qr-generator/', views.qr_generator_view, name='qr_generator'),
    path('rate/<int:event_id>/<int:speaker_id>/', views.submit_feedback_view, name='rate_speaker'),
    path('thanks/', views.thank_you_view, name='thank_you'),
    path('events/request-create/', views.submit_event_request_view, name='submit_event_request'),
    path('events/<int:event_id>/request-join/', views.submit_join_request_view, name='submit_join_request'),
    path('api/my-event-requests/', views.my_event_requests_api, name='my_event_requests_api'),
    path('events/admin/create/', views.admin_event_create, name='admin_event_create'),
    path('events/admin/<int:event_id>/edit/', views.admin_event_edit, name='admin_event_edit'),
    path('events/admin/<int:event_id>/delete/', views.admin_event_delete, name='admin_event_delete'),
    path('events/admin/<int:event_id>/remove-speaker/<int:speaker_id>/', views.admin_event_remove_speaker, name='admin_event_remove_speaker'),
    path('api/admin/pending-requests/', views.admin_pending_requests_api, name='admin_pending_requests_api'),
    path('api/admin/quick-approve/<int:request_id>/', views.admin_quick_approve, name='admin_quick_approve'),
    path('assistant/', include('assistant.urls')),
    path('assistant/support/', include(('support.urls', 'support'), namespace='support')),
    path('support/', include(('support.urls_guest', 'support_guest'), namespace='support_guest')),
    path('api/notifications/', views.notifications_api, name='notifications_api'),
]

if settings.MEDIA_URL.startswith("/"):
    if settings.DEBUG:
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    else:
        # In production there is no nginx in front of gunicorn, so Django itself
        # serves user-uploaded media. Object storage bypasses this branch.
        media_prefix = settings.MEDIA_URL.lstrip("/")
        urlpatterns += [
            re_path(
                rf"^{media_prefix}(?P<path>.*)$",
                static_serve,
                {"document_root": settings.MEDIA_ROOT},
            ),
        ]

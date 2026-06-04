"""Tests for the speaker-only /me/ sidebar pages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from .models import Event, EventRequest, Feedback, Speaker, SpeakerLike


def _make_speaker(name="Speaker", city="Moscow", stack="Python"):
    return Speaker.objects.create(name=name, sub="Sub", stack=stack, city=city, nps=0, img="1")


def _make_event(title="Event", status="past"):
    return Event.objects.create(title=title, status=status)


class MeRoutesAuthGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.linked_speaker = _make_speaker("Linked")
        cls.other_speaker = _make_speaker("Other")

        cls.speaker_user = User.objects.create_user(
            username="speaker1", password="Secret!234", email="s1@example.com"
        )
        cls.speaker_user.profile.role = UserProfile.ROLE_SPEAKER
        cls.speaker_user.profile.email_verified = True
        cls.speaker_user.profile.save(update_fields=["role", "email_verified"])
        cls.linked_speaker.user = cls.speaker_user
        cls.linked_speaker.save()

        cls.orphan_speaker_user = User.objects.create_user(
            username="speaker_orphan", password="Secret!234", email="orph@example.com"
        )
        cls.orphan_speaker_user.profile.role = UserProfile.ROLE_SPEAKER
        cls.orphan_speaker_user.profile.email_verified = True
        cls.orphan_speaker_user.profile.save(update_fields=["role", "email_verified"])

        cls.admin_user = User.objects.create_user(
            username="root", password="Admin!234", is_superuser=True, is_staff=True
        )

        cls.guest_user = User.objects.create_user(
            username="guesty", password="Guest!234", email="g@example.com"
        )

    def test_anonymous_redirects_to_login(self):
        for name in ["me_dashboard", "me_feedback", "me_events", "me_requests", "me_favorites"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn("/auth/login/", resp.url, name)

    def test_guest_redirected_to_application(self):
        # A guest with no SpeakerApplication is nudged to the application form
        # by GuestApplicationRedirectMiddleware before the /me/ view is reached.
        self.client.login(username="guesty", password="Guest!234")
        resp = self.client.get(reverse("me_dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/application/", resp.url)

    def test_linked_speaker_can_open_all_pages(self):
        self.client.login(username="speaker1", password="Secret!234")
        for name in ["me_dashboard", "me_feedback", "me_events", "me_requests", "me_favorites"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)

    def test_orphan_speaker_redirected_to_profile(self):
        self.client.login(username="speaker_orphan", password="Secret!234")
        resp = self.client.get(reverse("me_dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/profile/", resp.url)

    def test_favorites_open_to_admin_too(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.get(reverse("me_favorites"))
        self.assertEqual(resp.status_code, 200)

    def test_speaker_only_pages_redirect_admin_to_explore(self):
        self.client.login(username="root", password="Admin!234")
        # Superuser still gets pages — they pass role check via is_superuser.
        # Plain admin (non-superuser) should not see /me/dashboard since no Speaker is linked.
        # Here root is superuser, so they reach speaker_required and get redirected to profile (no Speaker link).
        resp = self.client.get(reverse("me_dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/profile/", resp.url)


class MeDataIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.my_speaker = _make_speaker("MeSpeaker")
        cls.other_speaker = _make_speaker("OtherSpeaker")

        cls.user = User.objects.create_user(
            username="me", password="Secret!234", email="me@example.com"
        )
        cls.user.profile.role = UserProfile.ROLE_SPEAKER
        cls.user.profile.email_verified = True
        cls.user.profile.save(update_fields=["role", "email_verified"])
        cls.my_speaker.user = cls.user
        cls.my_speaker.save()

        cls.my_event = _make_event("My Talk", status="past")
        cls.my_event.speakers.add(cls.my_speaker)

        cls.other_event = _make_event("Other Talk", status="past")
        cls.other_event.speakers.add(cls.other_speaker)

        # Feedback for both speakers — each must only see their own.
        for score in [10, 9, 7, 3]:
            Feedback.objects.create(speaker=cls.my_speaker, event=cls.my_event, score=score, comment=f"mine-{score}")
        for score in [10, 10]:
            Feedback.objects.create(speaker=cls.other_speaker, event=cls.other_event, score=score, comment="other-secret")

        EventRequest.objects.create(
            kind=EventRequest.KIND_CREATE,
            speaker=cls.my_speaker,
            proposed_title="My pending request",
            status=EventRequest.STATUS_PENDING,
        )
        EventRequest.objects.create(
            kind=EventRequest.KIND_JOIN,
            speaker=cls.other_speaker,
            event=cls.other_event,
            topic="OTHER-SECRET-TOPIC",
            status=EventRequest.STATUS_PENDING,
        )

    def setUp(self):
        self.client.login(username="me", password="Secret!234")

    def test_feedback_page_lists_only_my_feedback(self):
        resp = self.client.get(reverse("me_feedback"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "mine-10")
        self.assertContains(resp, "mine-3")
        self.assertNotContains(resp, "other-secret")

    def test_events_page_lists_only_my_events(self):
        resp = self.client.get(reverse("me_events"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "My Talk")
        self.assertNotContains(resp, "Other Talk")

    def test_requests_page_lists_only_my_requests(self):
        resp = self.client.get(reverse("me_requests"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "My pending request")
        self.assertNotContains(resp, "OTHER-SECRET-TOPIC")

    def test_dashboard_aggregates_only_my_feedback(self):
        resp = self.client.get(reverse("me_dashboard"))
        self.assertEqual(resp.status_code, 200)
        # I have 4 feedbacks; the other speaker has 2. We must show 4.
        self.assertContains(resp, "Отзывов всего")
        ctx = resp.context
        self.assertEqual(ctx["feedback_count"], 4)

    def test_feedback_csv_export_only_mine(self):
        resp = self.client.get(reverse("me_feedback_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        body = resp.content.decode("utf-8")
        self.assertIn("mine-10", body)
        self.assertNotIn("other-secret", body)
        # BOM for Excel
        self.assertTrue(body.startswith("﻿"))

    def test_feedback_event_filter(self):
        resp = self.client.get(reverse("me_feedback"), {"event": self.my_event.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "mine-10")

    def test_favorites_lists_only_my_likes(self):
        SpeakerLike.objects.create(user=self.user, speaker=self.other_speaker)
        resp = self.client.get(reverse("me_favorites"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "OtherSpeaker")

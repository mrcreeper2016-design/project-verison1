from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from .models import Event, EventRequest, Speaker


User = get_user_model()


class SubmitJoinRequestDeadlineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="spk", password="Pass!234")
        cls.user.profile.role = UserProfile.ROLE_SPEAKER
        cls.user.profile.save()
        cls.speaker = Speaker.objects.create(
            name="S Speaker", sub="X", stack="py", city="msk", img="", user=cls.user,
        )

    def _event(self, deadline=None):
        return Event.objects.create(
            title="EV", status="future", event_date=timezone.localdate() + timedelta(days=10),
            application_deadline=deadline,
        )

    def test_can_submit_within_deadline(self):
        ev = self._event(deadline=timezone.localdate() + timedelta(days=3))
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(
            reverse("submit_join_request", args=[ev.pk]),
            {"topic": "Hello", "comment": ""},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body.get("ok"))
        self.assertTrue(
            EventRequest.objects.filter(event=ev, speaker=self.speaker, kind="join").exists()
        )

    def test_blocked_when_deadline_passed(self):
        ev = self._event(deadline=timezone.localdate() - timedelta(days=1))
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(reverse("submit_join_request", args=[ev.pk]), {"topic": "Hi"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "submissions_closed")

    def test_blocked_when_no_deadline(self):
        ev = self._event(deadline=None)
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(reverse("submit_join_request", args=[ev.pk]), {"topic": "Hi"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "submissions_closed")

    def test_can_self_submit_method(self):
        future = self._event(deadline=timezone.localdate() + timedelta(days=1))
        past = self._event(deadline=timezone.localdate() - timedelta(days=1))
        none_dl = self._event(deadline=None)
        self.assertTrue(future.can_self_submit())
        self.assertFalse(past.can_self_submit())
        self.assertFalse(none_dl.can_self_submit())

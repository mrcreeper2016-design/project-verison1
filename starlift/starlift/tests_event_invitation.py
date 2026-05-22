from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from .models import Event, EventInvitation, Speaker


User = get_user_model()


def _make_user(username, role, company=""):
    u = User.objects.create_user(username=username, password="Pass!234")
    u.profile.role = role
    u.profile.company = company
    u.profile.save()
    return u


class DevRelInvitationCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.devrel_sber = _make_user("dr_s", UserProfile.ROLE_DEVREL, "Сбер")
        cls.devrel_tin = _make_user("dr_t", UserProfile.ROLE_DEVREL, "Т-Банк")
        cls.admin = _make_user("adm", UserProfile.ROLE_ADMIN)
        cls.spk_sber_user = _make_user("u_sber", UserProfile.ROLE_SPEAKER, "Сбер")
        cls.spk_sber = Speaker.objects.create(name="Speaker Sber", sub="Сбер", stack="py", city="m", img="", user=cls.spk_sber_user)
        cls.spk_tin_user = _make_user("u_tin", UserProfile.ROLE_SPEAKER, "Т-Банк")
        cls.spk_tin = Speaker.objects.create(name="Speaker Tin", sub="Т-Банк", stack="py", city="m", img="", user=cls.spk_tin_user)
        cls.event = Event.objects.create(
            title="EV", status="future",
            event_date=timezone.localdate() + timedelta(days=30),
            application_deadline=timezone.localdate() + timedelta(days=3),
        )
        # Событие без event_date вообще → дедлайн не автозаполняется, остаётся None.
        cls.event_no_dl = Event.objects.create(
            title="No-DL", status="future",
            event_date=None,
            application_deadline=None,
        )

    def test_devrel_invites_own_company_speaker(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:event_invite", args=[self.event.pk]),
            {"speaker_id": self.spk_sber.pk, "message": "Привет"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            EventInvitation.objects.filter(
                event=self.event, speaker=self.spk_sber, status="pending",
            ).exists()
        )

    def test_devrel_cannot_invite_other_company_speaker(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:event_invite", args=[self.event.pk]),
            {"speaker_id": self.spk_tin.pk, "message": ""},
        )
        # либо 302 c сообщением об ошибке, либо 404 — главное: invitation НЕ создалась.
        self.assertFalse(
            EventInvitation.objects.filter(event=self.event, speaker=self.spk_tin).exists()
        )

    def test_admin_can_invite_any_speaker(self):
        self.client.login(username="adm", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:event_invite", args=[self.event.pk]),
            {"speaker_id": self.spk_tin.pk, "message": ""},
        )
        self.assertTrue(
            EventInvitation.objects.filter(event=self.event, speaker=self.spk_tin).exists()
        )

    def test_can_invite_to_event_without_deadline(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:event_invite", args=[self.event_no_dl.pk]),
            {"speaker_id": self.spk_sber.pk, "message": ""},
        )
        self.assertTrue(
            EventInvitation.objects.filter(event=self.event_no_dl, speaker=self.spk_sber).exists()
        )

    def test_duplicate_pending_blocked(self):
        EventInvitation.objects.create(event=self.event, speaker=self.spk_sber, invited_by=self.devrel_sber)
        self.client.login(username="dr_s", password="Pass!234")
        self.client.post(
            reverse("accounts:event_invite", args=[self.event.pk]),
            {"speaker_id": self.spk_sber.pk, "message": ""},
        )
        # должна остаться одна
        self.assertEqual(
            EventInvitation.objects.filter(event=self.event, speaker=self.spk_sber).count(), 1
        )


class SpeakerInvitationResponseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _make_user("spk", UserProfile.ROLE_SPEAKER, "Сбер")
        cls.speaker = Speaker.objects.create(name="N", sub="Сбер", stack="py", city="m", img="", user=cls.user)
        cls.devrel = _make_user("dr", UserProfile.ROLE_DEVREL, "Сбер")
        cls.event = Event.objects.create(
            title="EV", status="future",
            event_date=timezone.localdate() + timedelta(days=30),
            application_deadline=timezone.localdate() + timedelta(days=3),
        )

    def _inv(self):
        return EventInvitation.objects.create(event=self.event, speaker=self.speaker, invited_by=self.devrel)

    def test_speaker_accepts_invitation(self):
        inv = self._inv()
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(reverse("me_invitation_accept", args=[inv.pk]))
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "accepted")
        self.assertTrue(self.event.speakers.filter(pk=self.speaker.pk).exists())

    def test_speaker_declines_invitation(self):
        inv = self._inv()
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(
            reverse("me_invitation_decline", args=[inv.pk]),
            {"decline_reason": "занят"},
        )
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "declined")
        self.assertEqual(inv.decline_reason, "занят")
        self.assertFalse(self.event.speakers.filter(pk=self.speaker.pk).exists())

    def test_other_speaker_cannot_respond(self):
        inv = self._inv()
        other = _make_user("other", UserProfile.ROLE_SPEAKER, "Сбер")
        Speaker.objects.create(name="O", sub="Сбер", stack="py", city="m", img="", user=other)
        self.client.login(username="other", password="Pass!234")
        resp = self.client.post(reverse("me_invitation_accept", args=[inv.pk]))
        inv.refresh_from_db()
        self.assertEqual(inv.status, "pending")


class DevRelCancelInvitationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.devrel = _make_user("dr", UserProfile.ROLE_DEVREL, "Сбер")
        cls.spk_user = _make_user("spk", UserProfile.ROLE_SPEAKER, "Сбер")
        cls.speaker = Speaker.objects.create(name="N", sub="Сбер", stack="py", city="m", img="", user=cls.spk_user)
        cls.event = Event.objects.create(title="E", status="future", application_deadline=timezone.localdate() + timedelta(days=3))

    def test_devrel_cancels_invitation(self):
        inv = EventInvitation.objects.create(event=self.event, speaker=self.speaker, invited_by=self.devrel)
        self.client.login(username="dr", password="Pass!234")
        resp = self.client.post(reverse("accounts:event_invitation_cancel", args=[inv.pk]))
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertEqual(inv.status, "cancelled")

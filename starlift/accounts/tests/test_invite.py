from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Invite, UserProfile
from accounts.services import tokens as token_svc
from starlift.models import Speaker


User = get_user_model()


class InviteFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="root", email="root@example.com", password="Admin!234", is_superuser=True, is_staff=True)
        cls.speaker_person = User.objects.create_user(username="vasya", email="vasya@example.com", password="Secret!234")
        cls.speaker_person.profile.role = UserProfile.ROLE_SPEAKER
        cls.speaker_person.profile.save()
        cls.speaker = Speaker.objects.create(name="Петр Петров", sub="Senior", stack="py,go", city="Москва", img="p.jpg")

    def test_speaker_cannot_see_invites(self):
        self.client.login(username="vasya", password="Secret!234")
        resp = self.client.get(reverse("accounts:invites"))
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_create_invite(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:invites"),
            {"email": "newbie@example.com", "role": "speaker", "send_email": "on", "speaker": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Invite.objects.filter(email="newbie@example.com").exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_INVITE_CREATED).exists())

    def test_duplicate_active_invite_rejected(self):
        self.client.login(username="root", password="Admin!234")
        self.client.post(reverse("accounts:invites"), {"email": "dup@example.com", "role": "speaker", "send_email": "on", "speaker": ""})
        resp = self.client.post(reverse("accounts:invites"), {"email": "dup@example.com", "role": "speaker", "send_email": "on", "speaker": ""})
        self.assertContains(resp, "Активный инвайт", status_code=200)

    def test_invite_email_uniqueness_vs_existing_user(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(reverse("accounts:invites"), {"email": "vasya@example.com", "role": "speaker", "send_email": "on", "speaker": ""})
        self.assertContains(resp, "уже зарегистрирован", status_code=200)

    def test_admin_can_revoke_invite(self):
        self.client.login(username="root", password="Admin!234")
        raw = token_svc.make_token()
        inv = Invite.objects.create(
            email="x@example.com", role="speaker", token_hash=token_svc.hash_token(raw),
            expires_at=timezone.now() + timedelta(days=1), created_by=self.admin,
        )
        resp = self.client.post(reverse("accounts:invite_revoke", args=[inv.pk]))
        self.assertEqual(resp.status_code, 302)
        inv.refresh_from_db()
        self.assertIsNotNone(inv.revoked_at)

    def _make_invite(self, email="newbie@example.com", speaker=None, role="speaker"):
        raw = token_svc.make_token()
        inv = Invite.objects.create(
            email=email, role=role, token_hash=token_svc.hash_token(raw),
            expires_at=timezone.now() + timedelta(days=1), created_by=self.admin,
            speaker=speaker,
        )
        return raw, inv

    def test_accept_invite_creates_user_and_logs_in(self):
        raw, inv = self._make_invite()
        resp = self.client.get(reverse("accounts:invite_accept", args=[raw]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            reverse("accounts:invite_accept", args=[raw]),
            {"username": "newbie", "first_name": "N", "last_name": "B", "password1": "NewPass!9", "password2": "NewPass!9"},
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username="newbie")
        self.assertEqual(user.email, "newbie@example.com")
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(user.profile.role, "speaker")
        inv.refresh_from_db()
        self.assertIsNotNone(inv.used_at)
        self.assertEqual(inv.consumed_by_id, user.pk)

    def test_accept_invite_links_speaker(self):
        raw, inv = self._make_invite(speaker=self.speaker)
        self.client.post(
            reverse("accounts:invite_accept", args=[raw]),
            {"username": "petrp", "first_name": "P", "last_name": "P", "password1": "NewPass!9", "password2": "NewPass!9"},
        )
        self.speaker.refresh_from_db()
        new_user = User.objects.get(username="petrp")
        self.assertEqual(self.speaker.user_id, new_user.pk)
        self.assertEqual(self.speaker.status, Speaker.STATUS_AUTHORIZED)

    def test_accept_invalid_token_410(self):
        resp = self.client.get(reverse("accounts:invite_accept", args=["invalidtoken"]))
        self.assertEqual(resp.status_code, 410)

    def test_accept_used_token_410(self):
        raw, inv = self._make_invite()
        inv.used_at = timezone.now()
        inv.save(update_fields=["used_at"])
        resp = self.client.get(reverse("accounts:invite_accept", args=[raw]))
        self.assertEqual(resp.status_code, 410)

    def test_accept_expired_token_410(self):
        raw, inv = self._make_invite()
        inv.expires_at = timezone.now() - timedelta(seconds=1)
        inv.save(update_fields=["expires_at"])
        resp = self.client.get(reverse("accounts:invite_accept", args=[raw]))
        self.assertEqual(resp.status_code, 410)

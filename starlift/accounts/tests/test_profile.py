import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import AuditLog, EmailVerification, UserProfile
from starlift.forms import SpeakerForm
from starlift.models import Speaker


User = get_user_model()


class ProfileEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", email="alice@example.com", password="Secret!234", first_name="Alice", last_name="A")

    def test_requires_login(self):
        resp = self.client.get(reverse("accounts:profile"))
        self.assertEqual(resp.status_code, 302)

    def test_edit_name_and_bio(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(reverse("accounts:profile"), {"first_name": "Alisa", "last_name": "A", "bio": "Hello"})
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Alisa")
        self.assertEqual(self.user.profile.bio, "Hello")
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_PROFILE_UPDATED, actor=self.user).exists())


class EmailChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", email="alice@example.com", password="Secret!234")

    def test_email_change_sends_email_and_verifies(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "alice2@example.com", "current_password": "Secret!234"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

        body = mail.outbox[0].body + (mail.outbox[0].alternatives[0][0] if mail.outbox[0].alternatives else "")
        m = re.search(r"/auth/email/verify/([^/\s]+)/", body)
        self.assertIsNotNone(m)
        token = m.group(1)

        resp = self.client.get(reverse("accounts:verify_email", args=[token]))
        self.assertEqual(resp.status_code, 302)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "alice2@example.com")
        self.assertTrue(self.user.profile.email_verified)
        self.assertIsNone(self.user.profile.pending_email)
        self.assertTrue(EmailVerification.objects.get(user=self.user).used_at is not None)

    def test_email_change_wrong_password(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "alice2@example.com", "current_password": "wrong"},
        )
        self.assertContains(resp, "Неверный пароль", status_code=200)

    def test_email_change_rejects_duplicate(self):
        User.objects.create_user(username="bob", email="bob@example.com", password="Secret!234")
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "bob@example.com", "current_password": "Secret!234"},
        )
        self.assertContains(resp, "уже используется", status_code=200)

    def test_verify_with_invalid_token(self):
        resp = self.client.get(reverse("accounts:verify_email", args=["badtoken"]))
        self.assertEqual(resp.status_code, 410)


class SpeakerFormGuardTests(TestCase):
    """Ensure the speaker admin form cannot be tricked into writing NPS/status."""

    def test_whitelist_fields_only(self):
        form = SpeakerForm(data={
            "name": "X", "stack": "py", "city": "Msk", "img": "x.jpg", "recommended": True,
            "status": "closed", "nps": 999, "sub": "evil", "bio": "no-edit-here",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("status", form.fields)
        self.assertNotIn("nps", form.fields)
        self.assertNotIn("sub", form.fields)
        self.assertNotIn("bio", form.fields)

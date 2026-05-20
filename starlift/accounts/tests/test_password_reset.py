import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class PasswordResetFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", email="alice@example.com", password="Secret!234")

    def test_reset_sends_email_and_completes_flow(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "alice@example.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body + (mail.outbox[0].alternatives[0][0] if mail.outbox[0].alternatives else "")
        m = re.search(r"/auth/reset/([^/\s]+)/([^/\s]+)/", body)
        self.assertIsNotNone(m)
        uidb64, token = m.group(1), m.group(2)

        # Follow the confirm URL — Django's CBV swaps the token for a session marker
        # and redirects to the set-password form.
        confirm_url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
        resp = self.client.get(confirm_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Submit new password on the redirected form.
        final_url = resp.request["PATH_INFO"]
        resp = self.client.post(
            final_url,
            {"new_password1": "BrandNew!9", "new_password2": "BrandNew!9"},
        )
        self.assertRedirects(resp, reverse("accounts:password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("BrandNew!9"))

    def test_reset_for_unknown_email_silently_succeeds(self):
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_change_requires_login(self):
        resp = self.client.get(reverse("accounts:password_change"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login/", resp.url)

    def test_password_change_success(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": "Secret!234", "new_password1": "Another!77", "new_password2": "Another!77"},
        )
        self.assertRedirects(resp, reverse("accounts:password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Another!77"))

    def test_password_change_rejects_weak(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": "Secret!234", "new_password1": "12345678", "new_password2": "12345678"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "пароль")

    def test_password_change_rejects_only_special(self):
        self.client.login(username="alice", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:password_change"),
            {"old_password": "Secret!234", "new_password1": "!!!!!!!!", "new_password2": "!!!!!!!!"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "специальных")

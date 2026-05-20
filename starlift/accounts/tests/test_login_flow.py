from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AuditLog, LoginAttempt


User = get_user_model()


@override_settings(ACCOUNTS_LOCKOUT_THRESHOLD=3, ACCOUNTS_LOCKOUT_WINDOW_SECONDS=60)
class LoginFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", email="alice@example.com", password="Secret!234")

    def test_get_login_page(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Войти")

    def test_login_success_by_username(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "Secret!234"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN_SUCCESS, actor=self.user).exists())

    def test_login_success_by_email(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "alice@example.com", "password": "Secret!234"})
        self.assertEqual(resp.status_code, 302)

    def test_login_failed_records_attempt_and_audit(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Неверное")
        self.assertEqual(LoginAttempt.objects.filter(username_or_email="alice", success=False).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_LOGIN_FAILED).exists())

    def test_login_lockout_after_threshold(self):
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"username": "alice", "password": "wrong"})
        resp = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "Secret!234"})
        self.assertContains(resp, "Слишком много неудачных попыток", status_code=200)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_LOCKOUT_TRIGGERED).exists())

    def test_login_redirects_safe_next(self):
        resp = self.client.post(
            reverse("accounts:login") + "?next=/speakers/",
            {"username": "alice", "password": "Secret!234"},
        )
        self.assertRedirects(resp, "/speakers/", fetch_redirect_response=False)

    def test_login_rejects_unsafe_next(self):
        resp = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example/",
            {"username": "alice", "password": "Secret!234"},
        )
        self.assertRedirects(resp, "/", fetch_redirect_response=False)

    def test_inactive_user_cannot_login(self):
        # Make sure we're testing the "admin deactivated a verified user" path
        # — otherwise the login view (correctly) shows a "verify your email"
        # hint for unverified guests whose password is right.
        self.user.profile.email_verified = True
        self.user.profile.save(update_fields=["email_verified"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        resp = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "Secret!234"})
        self.assertContains(resp, "Неверное", status_code=200)

    def test_inactive_unverified_user_sees_verify_hint(self):
        # Complementary coverage for the self-registration path: guest whose
        # email is not verified should get the specific "check your email"
        # message rather than the generic "invalid credentials".
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.user.profile.email_verified = False
        self.user.profile.save(update_fields=["email_verified"])
        resp = self.client.post(reverse("accounts:login"), {"username": "alice", "password": "Secret!234"})
        self.assertContains(resp, "Email не подтверждён", status_code=200)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        resp_get = self.client.get(reverse("accounts:logout"))
        self.assertEqual(resp_get.status_code, 200)  # confirm page
        resp = self.client.post(reverse("accounts:logout"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_LOGOUT, actor=self.user).exists())

    def test_protected_page_redirects_anonymous(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login/", resp.url)

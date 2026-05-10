"""Self-service registration, email verification and guest->speaker promotion."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, EmailVerification, Invite, UserProfile
from accounts.services import tokens as token_svc


User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegisterViewTests(TestCase):
    def test_register_page_renders(self):
        resp = self.client.get(reverse("accounts:register"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Создание аккаунта")

    def test_register_redirects_logged_in_user(self):
        u = User.objects.create_user(username="admin1", email="a@b.ru", password="Secret!234")
        u.profile.role = UserProfile.ROLE_ADMIN
        u.profile.email_verified = True
        u.profile.save()
        self.client.login(username="admin1", password="Secret!234")
        resp = self.client.get(reverse("accounts:register"))
        self.assertEqual(resp.status_code, 302)

    def test_successful_registration_creates_inactive_guest(self):
        mail.outbox.clear()
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "gleb",
                "first_name": "Gleb",
                "last_name": "Petrov",
                "email": "gleb@example.com",
                "password1": "MyStrongPass!9",
                "password2": "MyStrongPass!9",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/register/pending/", resp["Location"])

        u = User.objects.get(username="gleb")
        self.assertEqual(u.email, "gleb@example.com")
        self.assertFalse(u.is_active, "newly-registered user must be inactive until email verified")
        self.assertEqual(u.profile.role, UserProfile.ROLE_GUEST)
        self.assertFalse(u.profile.email_verified)

        self.assertEqual(EmailVerification.objects.filter(user=u, used_at__isnull=True).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(u.email, mail.outbox[0].to)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.ACTION_GUEST_REGISTERED, target_id=str(u.pk)).exists()
        )

    def test_duplicate_username_rejected(self):
        User.objects.create_user(username="exists", email="x@y.ru", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "exists",
                "first_name": "",
                "last_name": "",
                "email": "fresh@example.com",
                "password1": "MyStrongPass!9",
                "password2": "MyStrongPass!9",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertContains(resp, "уже занято", status_code=200)
        self.assertFalse(User.objects.filter(email="fresh@example.com").exists())

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username="who", email="taken@example.com", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "other",
                "first_name": "",
                "last_name": "",
                "email": "TAKEN@example.com",
                "password1": "MyStrongPass!9",
                "password2": "MyStrongPass!9",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertContains(resp, "уже зарегистрирован", status_code=200)
        self.assertFalse(User.objects.filter(username="other").exists())

    def test_register_rejected_when_active_invite_exists(self):
        admin = User.objects.create_user(
            username="rootforinvite", email="rfi@example.com",
            password="Admin!234", is_superuser=True, is_staff=True,
        )
        raw = token_svc.make_token()
        Invite.objects.create(
            email="invited@example.com",
            role="speaker",
            token_hash=token_svc.hash_token(raw),
            expires_at=timezone.now() + timedelta(days=1),
            created_by=admin,
        )
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "selfinvited",
                "first_name": "",
                "last_name": "",
                "email": "invited@example.com",
                "password1": "MyStrongPass!9",
                "password2": "MyStrongPass!9",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertContains(resp, "приглашение", status_code=200)
        self.assertFalse(User.objects.filter(username="selfinvited").exists())

    def test_weak_password_rejected(self):
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "weak",
                "first_name": "",
                "last_name": "",
                "email": "weak@example.com",
                "password1": "1234567",
                "password2": "1234567",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="weak").exists())

    def test_password_mismatch_rejected(self):
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "username": "mismatch",
                "first_name": "",
                "last_name": "",
                "email": "m@example.com",
                "password1": "StrongPass!9",
                "password2": "StrongPass!8",
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        self.assertContains(resp, "не совпадают", status_code=200)
        self.assertFalse(User.objects.filter(username="mismatch").exists())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegisterActivationTests(TestCase):
    def _register(self, username="gleb", email="gleb@example.com", password="MyStrongPass!9"):
        mail.outbox.clear()
        self.client.post(
            reverse("accounts:register"),
            {
                "username": username,
                "first_name": "",
                "last_name": "",
                "email": email,
                "password1": password,
                "password2": password,
                "consent_pdn": "on",
                "accept_policy": "on",
            },
        )
        return User.objects.get(username=username)

    def test_inactive_user_cannot_login_with_correct_password(self):
        self._register()
        ok = self.client.login(username="gleb", password="MyStrongPass!9")
        self.assertFalse(ok)

    def test_login_view_tells_inactive_user_to_verify(self):
        self._register()
        resp = self.client.post(
            reverse("accounts:login"),
            {"username": "gleb", "password": "MyStrongPass!9"},
        )
        self.assertContains(resp, "Email не подтверждён", status_code=200)

    def test_verification_activates_user(self):
        user = self._register()
        rec = EmailVerification.objects.filter(user=user, used_at__isnull=True).first()
        self.assertIsNotNone(rec)
        body = mail.outbox[0].body + (mail.outbox[0].alternatives[0][0] if mail.outbox[0].alternatives else "")
        # Recover raw token from the email link; token is in the URL path.
        import re
        m = re.search(r"/auth/email/verify/([^/\s\"'>]+)/", body)
        self.assertIsNotNone(m, "verification link missing from email body")
        raw = m.group(1)

        resp = self.client.get(reverse("accounts:verify_email", args=[raw]))
        self.assertEqual(resp.status_code, 200)

        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)
        rec.refresh_from_db()
        self.assertIsNotNone(rec.used_at)

        # Now login works.
        self.assertTrue(self.client.login(username="gleb", password="MyStrongPass!9"))

    def test_audit_logs_email_verified_for_registration_flow(self):
        user = self._register()
        rec = EmailVerification.objects.get(user=user, used_at__isnull=True)
        # Build link directly — by this point we don't need to parse from email.
        raw = token_svc.make_token()
        # Instead, re-create the record with a known raw:
        EmailVerification.objects.filter(pk=rec.pk).delete()
        EmailVerification.objects.create(
            user=user,
            new_email=user.email,
            token_hash=token_svc.hash_token(raw),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.client.get(reverse("accounts:verify_email", args=[raw]))
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ACTION_EMAIL_VERIFIED, target_id=str(user.pk)
            ).exists(),
            "registration verification must emit an `email_verified` audit event",
        )


class GuestAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.guest = User.objects.create_user(
            username="g1", email="g1@example.com", password="GuestPass!9"
        )
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.email_verified = True
        cls.guest.profile.save()

    def test_guest_redirected_from_home_to_explore(self):
        self.client.login(username="g1", password="GuestPass!9")
        resp = self.client.get(reverse("home"), follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/explore/")

    def test_guest_can_access_explore(self):
        self.client.login(username="g1", password="GuestPass!9")
        resp = self.client.get(reverse("explore"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Обзор")

    def test_guest_redirected_from_speakers(self):
        self.client.login(username="g1", password="GuestPass!9")
        resp = self.client.get(reverse("speakers"), follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/explore/")

    def test_guest_redirected_from_analytics(self):
        self.client.login(username="g1", password="GuestPass!9")
        resp = self.client.get(reverse("analytics"), follow=False)
        self.assertEqual(resp.status_code, 302)

    def test_guest_cannot_see_console(self):
        self.client.login(username="g1", password="GuestPass!9")
        resp = self.client.get(reverse("accounts:users"))
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected_from_explore_to_login(self):
        resp = self.client.get(reverse("explore"), follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login/", resp["Location"])


class PromoteGuestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="root", email="root@example.com", password="Admin!234",
            is_superuser=True, is_staff=True,
        )
        cls.guest = User.objects.create_user(
            username="guest1", email="guest1@example.com", password="GuestPass!9",
        )
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.email_verified = True
        cls.guest.profile.save()

    def test_admin_promotes_guest_to_speaker(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:user_detail", args=[self.guest.pk]),
            {"action": "change_role", "role": "speaker"},
        )
        self.assertEqual(resp.status_code, 302)
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.profile.role, UserProfile.ROLE_SPEAKER)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.ACTION_GUEST_PROMOTED, target_id=str(self.guest.pk)
            ).exists()
        )

    def test_promoted_speaker_can_access_home(self):
        self.client.login(username="root", password="Admin!234")
        self.client.post(
            reverse("accounts:user_detail", args=[self.guest.pk]),
            {"action": "change_role", "role": "speaker"},
        )
        self.client.logout()
        self.client.login(username="guest1", password="GuestPass!9")
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_list_guests(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.get(reverse("accounts:users"), {"role": "guest"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.guest.username)

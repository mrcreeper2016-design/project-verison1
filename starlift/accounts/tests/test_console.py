from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import AuditLog, LoginAttempt, UserProfile
from accounts.services import lockout
from starlift.models import Speaker


User = get_user_model()


class ConsoleAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="root", email="root@example.com", password="Admin!234", is_superuser=True, is_staff=True)
        cls.speaker = User.objects.create_user(username="vasya", email="v@example.com", password="Secret!234")
        cls.speaker.profile.role = UserProfile.ROLE_SPEAKER
        cls.speaker.profile.save()
        cls.guest = User.objects.create_user(username="guest_ui", email="g@example.com", password="Guest!234")
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.email_verified = True
        cls.guest.profile.save()

    def test_speaker_forbidden(self):
        self.client.login(username="vasya", password="Secret!234")
        for name in ("accounts:users", "accounts:invites", "accounts:audit"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403, name)

    def test_admin_can_access(self):
        self.client.login(username="root", password="Admin!234")
        for name in ("accounts:users", "accounts:invites", "accounts:audit"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)

    def test_users_list_shows_inline_delete_button_for_guest(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.get(reverse("accounts:users"), {"role": "guest"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="action" value="delete_guest"', html=False)
        self.assertContains(resp, "Удалить")

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(reverse("accounts:users"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login/", resp.url)


class DevRelAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.devrel = User.objects.create_user(
            username="dr", email="dr@example.com", password="DevRel!234"
        )
        cls.devrel.profile.role = UserProfile.ROLE_DEVREL
        cls.devrel.profile.save()

    def setUp(self):
        self.client.login(username="dr", password="DevRel!234")

    def test_devrel_blocked_from_admin_only_console(self):
        for name in ("accounts:users", "accounts:audit"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403, name)

    def test_devrel_allowed_in_shared_console(self):
        for name in ("accounts:invites", "accounts:event_requests"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, name)

    def test_devrel_invite_form_rejects_admin_role(self):
        from accounts.forms import InviteCreateForm

        form = InviteCreateForm(
            data={"email": "new@example.com", "role": "admin", "send_email": "on"},
            actor=self.devrel,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("role", form.errors)

    def test_devrel_invite_form_accepts_speaker(self):
        from accounts.forms import InviteCreateForm

        form = InviteCreateForm(
            data={"email": "new@example.com", "role": "speaker", "send_email": "on"},
            actor=self.devrel,
        )
        self.assertTrue(form.is_valid(), form.errors)


class ConsoleOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="root", password="Admin!234", is_superuser=True, is_staff=True)
        cls.speaker = User.objects.create_user(username="vasya", password="Secret!234")
        cls.speaker.profile.role = UserProfile.ROLE_SPEAKER
        cls.speaker.profile.save()
        cls.guest = User.objects.create_user(username="guest_to_delete", password="Guest!234")
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.email_verified = True
        cls.guest.profile.save()
        cls.speaker_model = Speaker.objects.create(name="Петр", sub="M", stack="py", city="Msk", img="x")

    def setUp(self):
        self.client.login(username="root", password="Admin!234")

    def test_admin_unlock(self):
        for _ in range(6):
            LoginAttempt.objects.create(username_or_email="vasya", success=False)
        self.assertTrue(lockout.is_locked("vasya"))
        resp = self.client.post(reverse("accounts:user_detail", args=[self.speaker.pk]), {"action": "unlock"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(lockout.is_locked("vasya"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_LOCKOUT_LIFTED).exists())

    def test_admin_change_role(self):
        resp = self.client.post(reverse("accounts:user_detail", args=[self.speaker.pk]), {"action": "change_role", "role": "admin"})
        self.assertEqual(resp.status_code, 302)
        self.speaker.profile.refresh_from_db()
        self.assertEqual(self.speaker.profile.role, UserProfile.ROLE_ADMIN)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_ROLE_CHANGED).exists())

    def test_admin_toggle_active(self):
        resp = self.client.post(reverse("accounts:user_detail", args=[self.speaker.pk]), {"action": "toggle_active"})
        self.assertEqual(resp.status_code, 302)
        self.speaker.refresh_from_db()
        self.assertFalse(self.speaker.is_active)

    def test_admin_link_speaker(self):
        resp = self.client.post(
            reverse("accounts:user_detail", args=[self.speaker.pk]),
            {"action": "link_speaker", "speaker_id": str(self.speaker_model.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        self.speaker_model.refresh_from_db()
        self.assertEqual(self.speaker_model.user_id, self.speaker.pk)
        self.assertEqual(self.speaker_model.status, Speaker.STATUS_AUTHORIZED)

    def test_admin_unlink_speaker(self):
        self.speaker_model.user = self.speaker
        self.speaker_model.save()
        resp = self.client.post(
            reverse("accounts:user_detail", args=[self.speaker.pk]),
            {"action": "link_speaker", "speaker_id": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.speaker_model.refresh_from_db()
        self.assertIsNone(self.speaker_model.user_id)
        self.assertEqual(self.speaker_model.status, Speaker.STATUS_UNAUTHORIZED)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_SPEAKER_UNLINKED).exists())

    def test_admin_can_delete_guest_user(self):
        guest_pk = self.guest.pk
        resp = self.client.post(
            reverse("accounts:user_detail", args=[guest_pk]),
            {"action": "delete_guest"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("accounts:users"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(pk=guest_pk).exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.ACTION_GUEST_DELETED).exists())

    def test_admin_cannot_delete_non_guest_user_with_delete_guest_action(self):
        resp = self.client.post(
            reverse("accounts:user_detail", args=[self.speaker.pk]),
            {"action": "delete_guest"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.speaker.pk).exists())
        self.assertContains(resp, "Удаление разрешено только для пользователей с ролью «Гость».")

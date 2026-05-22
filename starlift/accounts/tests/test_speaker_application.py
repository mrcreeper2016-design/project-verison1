from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import AuditLog, UserProfile
from starlift.models import Speaker, SpeakerApplication


User = get_user_model()


class SpeakerApplicationFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.guest = User.objects.create_user(
            username="newbie", email="newbie@example.com", password="Guest!234"
        )
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.email_verified = True
        cls.guest.profile.save()

    def test_submit_creates_application(self):
        self.client.login(username="newbie", password="Guest!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_form"),
            {
                "company": "Сбер",
                "city": "Москва",
                "stack": "Python, Django",
                "description": "Бэкенд-разработчик 10 лет.",
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/application/pending/", resp["Location"])
        app = SpeakerApplication.objects.get(applicant=self.guest)
        self.assertEqual(app.status, SpeakerApplication.STATUS_PENDING)
        self.assertEqual(app.company, "Сбер")
        self.guest.profile.refresh_from_db()
        self.assertEqual(self.guest.profile.company, "Сбер")

    def test_resubmit_after_reject(self):
        SpeakerApplication.objects.create(
            applicant=self.guest,
            company="X",
            city="Y",
            stack="Z",
            description="...",
            status=SpeakerApplication.STATUS_REJECTED,
            rejection_reason="мало деталей",
        )
        self.client.login(username="newbie", password="Guest!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_form"),
            {
                "company": "X",
                "city": "Y2",
                "stack": "Z",
                "description": "Теперь больше деталей про опыт и темы выступлений.",
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        app = SpeakerApplication.objects.get(applicant=self.guest)
        self.assertEqual(app.status, SpeakerApplication.STATUS_PENDING)
        self.assertEqual(app.city, "Y2")
        self.assertEqual(app.rejection_reason, "")


class DevRelRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.devrel_sber = User.objects.create_user(username="dr_sber", password="DR!234")
        cls.devrel_sber.profile.role = UserProfile.ROLE_DEVREL
        cls.devrel_sber.profile.company = "Сбер"
        cls.devrel_sber.profile.save()

        cls.devrel_tinkoff = User.objects.create_user(username="dr_tin", password="DR!234")
        cls.devrel_tinkoff.profile.role = UserProfile.ROLE_DEVREL
        cls.devrel_tinkoff.profile.company = "Тинькофф"
        cls.devrel_tinkoff.profile.save()

        cls.admin = User.objects.create_user(username="root", password="Admin!234", is_superuser=True, is_staff=True)

        cls.guest_a = User.objects.create_user(username="ga", password="Pass!234")
        cls.guest_a.profile.role = UserProfile.ROLE_GUEST
        cls.guest_a.profile.save()
        cls.app_sber = SpeakerApplication.objects.create(
            applicant=cls.guest_a, company="Сбер", city="Msk", stack="py", description="...",
        )

        cls.guest_b = User.objects.create_user(username="gb", password="Pass!234")
        cls.guest_b.profile.role = UserProfile.ROLE_GUEST
        cls.guest_b.profile.save()
        cls.app_none = SpeakerApplication.objects.create(
            applicant=cls.guest_b, company="", city="Spb", stack="go", description="...",
        )

    def test_devrel_sees_own_company_and_blank(self):
        self.client.login(username="dr_sber", password="DR!234")
        resp = self.client.get(reverse("accounts:speaker_application_detail", args=[self.app_sber.pk]))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(reverse("accounts:speaker_application_detail", args=[self.app_none.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_devrel_blocked_from_other_company(self):
        self.client.login(username="dr_tin", password="DR!234")
        resp = self.client.get(
            reverse("accounts:speaker_application_detail", args=[self.app_sber.pk]),
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)

    def test_admin_sees_all(self):
        self.client.login(username="root", password="Admin!234")
        for app in (self.app_sber, self.app_none):
            resp = self.client.get(reverse("accounts:speaker_application_detail", args=[app.pk]))
            self.assertEqual(resp.status_code, 200)


class ApproveRejectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="root", password="Admin!234", is_superuser=True, is_staff=True)
        cls.guest = User.objects.create_user(
            username="bob", first_name="Bob", last_name="K", password="Pass!234",
        )
        cls.guest.profile.role = UserProfile.ROLE_GUEST
        cls.guest.profile.save()
        cls.app = SpeakerApplication.objects.create(
            applicant=cls.guest, company="Sber", city="Msk", stack="py", description="Bio",
        )

    def test_approve_creates_new_speaker(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_action", args=[self.app.pk, "approve"]),
            {"mode": "create"},
        )
        self.assertEqual(resp.status_code, 302)
        self.guest.profile.refresh_from_db()
        self.assertEqual(self.guest.profile.role, UserProfile.ROLE_SPEAKER)
        speaker = Speaker.objects.get(user=self.guest)
        self.assertEqual(speaker.sub, "Sber")
        self.assertEqual(speaker.city, "Msk")
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, SpeakerApplication.STATUS_APPROVED)
        self.assertEqual(self.app.resulting_speaker_id, speaker.pk)

    def test_approve_links_existing_speaker(self):
        existing = Speaker.objects.create(name="Bob K", sub="x", stack="y", city="z", img="i")
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_action", args=[self.app.pk, "approve"]),
            {"mode": "link", "speaker_id": str(existing.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.user_id, self.guest.pk)
        self.guest.profile.refresh_from_db()
        self.assertEqual(self.guest.profile.role, UserProfile.ROLE_SPEAKER)

    def test_reject_requires_reason(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_action", args=[self.app.pk, "reject"]),
            {},
        )
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, SpeakerApplication.STATUS_PENDING)

    def test_reject_with_reason(self):
        self.client.login(username="root", password="Admin!234")
        resp = self.client.post(
            reverse("accounts:speaker_application_action", args=[self.app.pk, "reject"]),
            {"rejection_reason": "недостаточно опыта"},
        )
        self.assertEqual(resp.status_code, 302)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, SpeakerApplication.STATUS_REJECTED)
        self.assertEqual(self.app.rejection_reason, "недостаточно опыта")
        self.guest.profile.refresh_from_db()
        self.assertEqual(self.guest.profile.role, UserProfile.ROLE_GUEST)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.ACTION_SPEAKER_APPLICATION_REJECTED).exists()
        )

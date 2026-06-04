from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import UserProfile
from .models import Event, EventPhoto, Speaker


User = get_user_model()


def _make_image(name="x.jpg", size=(50, 50), color=(10, 10, 10)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/jpeg")


class SpeakerEventUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="spk", password="Pass!234")
        cls.user.profile.role = UserProfile.ROLE_SPEAKER
        cls.user.profile.company = "Сбер"
        cls.user.profile.save()
        cls.speaker = Speaker.objects.create(
            name="Test Speaker", sub="Сбер", stack="py", city="msk", img="", user=cls.user,
        )

    def test_upload_creates_pending_event(self):
        self.client.login(username="spk", password="Pass!234")
        photo = _make_image()
        resp = self.client.post(
            reverse("me_event_upload"),
            {
                "title": "DjangoCon 2024",
                "event_date": (timezone.localdate() - timedelta(days=10)).isoformat(),
                "description": "Доклад про async views.",
                "format": "offline",
                "tags": "python, django",
                "video_url": "https://www.youtube.com/watch?v=abc",
                "photos": [photo],
            },
            follow=False,
        )
        self.assertEqual(resp.status_code, 302)
        ev = Event.objects.get(title="DjangoCon 2024")
        self.assertEqual(ev.verification_status, Event.VERIFICATION_PENDING)
        self.assertEqual(ev.submitted_by, self.user)
        self.assertEqual(ev.tags, "python, django")
        self.assertTrue(ev.speakers.filter(pk=self.speaker.pk).exists())
        self.assertEqual(ev.photos.count(), 1)

    def test_future_date_rejected(self):
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(
            reverse("me_event_upload"),
            {
                "title": "Future event",
                "event_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
                "description": "x",
            },
        )
        # Form should not redirect on error
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Event.objects.filter(title="Future event").exists())

    def test_invalid_video_url(self):
        self.client.login(username="spk", password="Pass!234")
        resp = self.client.post(
            reverse("me_event_upload"),
            {
                "title": "Bad video",
                "event_date": (timezone.localdate() - timedelta(days=5)).isoformat(),
                "description": "x",
                "video_url": "https://evil-host.example.com/v",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Event.objects.filter(title="Bad video").exists())


class PublicVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.viewer = User.objects.create_user(username="viewer", password="Pass!234")
        cls.viewer.profile.role = UserProfile.ROLE_ADMIN
        cls.viewer.profile.save()

        cls.pending = Event.objects.create(
            title="Hidden", status="past",
            event_date=timezone.localdate() - timedelta(days=10),
            verification_status=Event.VERIFICATION_PENDING,
        )
        cls.verified = Event.objects.create(
            title="Public", status="past",
            event_date=timezone.localdate() - timedelta(days=10),
            verification_status=Event.VERIFICATION_VERIFIED,
        )

    def test_events_api_excludes_pending(self):
        self.client.login(username="viewer", password="Pass!234")
        resp = self.client.get(reverse("events_api"))
        self.assertEqual(resp.status_code, 200)
        titles = [e["title"] for e in resp.json()]
        self.assertIn("Public", titles)
        self.assertNotIn("Hidden", titles)


class DevRelModerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.devrel_sber = User.objects.create_user(username="dr_s", password="Pass!234")
        cls.devrel_sber.profile.role = UserProfile.ROLE_DEVREL
        cls.devrel_sber.profile.company = "Сбер"
        cls.devrel_sber.profile.save()

        cls.devrel_tin = User.objects.create_user(username="dr_t", password="Pass!234")
        cls.devrel_tin.profile.role = UserProfile.ROLE_DEVREL
        cls.devrel_tin.profile.company = "Т-Банк"
        cls.devrel_tin.profile.save()

        cls.spk_user = User.objects.create_user(username="spk", password="Pass!234")
        cls.spk_user.profile.role = UserProfile.ROLE_SPEAKER
        cls.spk_user.profile.company = "Сбер"
        cls.spk_user.profile.save()

        cls.event = Event.objects.create(
            title="Submitted",
            status="past",
            event_date=timezone.localdate() - timedelta(days=5),
            verification_status=Event.VERIFICATION_PENDING,
            submitted_by=cls.spk_user,
        )

    def test_devrel_own_company_can_open_detail(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.get(reverse("accounts:speaker_event_detail", args=[self.event.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_devrel_other_company_blocked(self):
        self.client.login(username="dr_t", password="Pass!234")
        resp = self.client.get(reverse("accounts:speaker_event_detail", args=[self.event.pk]), follow=False)
        # Redirect to event_requests list
        self.assertEqual(resp.status_code, 302)

    def test_approve_makes_verified(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:speaker_event_action", args=[self.event.pk, "approve"]),
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.verification_status, Event.VERIFICATION_VERIFIED)
        self.assertEqual(self.event.verified_by, self.devrel_sber)

    def test_reject_requires_reason(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:speaker_event_action", args=[self.event.pk, "reject"]),
            {},
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.verification_status, Event.VERIFICATION_PENDING)

    def test_reject_with_reason(self):
        self.client.login(username="dr_s", password="Pass!234")
        resp = self.client.post(
            reverse("accounts:speaker_event_action", args=[self.event.pk, "reject"]),
            {"rejection_reason": "плохое описание"},
        )
        self.assertEqual(resp.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.verification_status, Event.VERIFICATION_REJECTED)
        self.assertEqual(self.event.rejection_reason, "плохое описание")


class SpeakerDeleteOwnPendingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="spk2", password="Pass!234")
        cls.user.profile.role = UserProfile.ROLE_SPEAKER
        cls.user.profile.save()
        cls.speaker = Speaker.objects.create(name="N", sub="x", stack="y", city="z", img="", user=cls.user)
        cls.event = Event.objects.create(
            title="Mine",
            status="past",
            event_date=timezone.localdate() - timedelta(days=5),
            verification_status=Event.VERIFICATION_PENDING,
            submitted_by=cls.user,
        )

    def test_delete_pending_own_event(self):
        self.client.login(username="spk2", password="Pass!234")
        resp = self.client.post(reverse("me_event_delete", args=[self.event.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())

    def test_cannot_delete_verified(self):
        self.event.verification_status = Event.VERIFICATION_VERIFIED
        self.event.save()
        self.client.login(username="spk2", password="Pass!234")
        resp = self.client.post(reverse("me_event_delete", args=[self.event.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())

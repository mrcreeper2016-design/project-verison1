import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.test.utils import override_settings
from PIL import Image

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


def _image_upload(name="avatar.png", size=(128, 128), color=(0, 128, 0)):
    buf = BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class AvatarMigrationTests(TestCase):
    def test_speaker_form_saves_avatar_file(self):
        form = SpeakerForm(
            data={
                "name": "Avatar User",
                "stack": "py",
                "city": "Msk",
                "img": "",
                "recommended": False,
            },
            files={"upload_image": _image_upload()},
        )
        self.assertTrue(form.is_valid(), form.errors)
        speaker = form.save()
        self.assertTrue(bool(speaker.avatar))
        self.assertTrue(speaker.avatar.name.startswith("avatars/speakers/"))

    def test_profile_update_accepts_avatar_upload(self):
        user = User.objects.create_user(username="avatar_u", email="au@example.com", password="Secret!234")
        self.client.login(username="avatar_u", password="Secret!234")
        resp = self.client.post(
            reverse("accounts:profile"),
            {
                "action": "profile",
                "first_name": "Avatar",
                "last_name": "User",
                "bio": "Bio",
                "avatar": _image_upload("profile.png"),
            },
        )
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(bool(user.profile.avatar))
        self.assertTrue(user.profile.avatar.name.startswith("avatars/users/"))

    def test_migrate_avatars_command_moves_legacy_media_files(self):
        with TemporaryDirectory() as media_dir:
            speakers_dir = Path(media_dir) / "speakers"
            speakers_dir.mkdir(parents=True, exist_ok=True)
            source = speakers_dir / "legacy.png"
            source.write_bytes(_image_upload("legacy.png").read())

            speaker = Speaker.objects.create(
                name="Legacy",
                sub="S",
                stack="py",
                city="Msk",
                nps=0,
                img="/media/speakers/legacy.png",
            )

            with override_settings(MEDIA_ROOT=media_dir, USE_OBJECT_STORAGE=False):
                call_command("migrate_avatars_to_object_storage")

            speaker.refresh_from_db()
            self.assertTrue(bool(speaker.avatar))
            self.assertTrue(speaker.avatar.name.startswith("avatars/speakers/"))

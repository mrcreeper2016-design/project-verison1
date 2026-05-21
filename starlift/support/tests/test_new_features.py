"""Tests for the redesigned features: avatars in API, typing presence."""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import UserProfile
from support.models import SupportTicket, SupportMessage


User = get_user_model()


def _make_user(username, role):
    u = User.objects.create_user(username=username, password="x", email=f"{username}@x.io")
    UserProfile.objects.update_or_create(user=u, defaults={"role": role})
    u.refresh_from_db()
    return u


@override_settings(MEDIA_ROOT="/tmp/test_media_support")
class ThreadApiAvatarTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_thread_api_returns_avatar_for_user_with_profile_photo(self):
        speaker = _make_user("av_speaker", "speaker")
        # Attach a profile avatar.
        img = SimpleUploadedFile("avatar.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png")
        speaker.profile.avatar = img
        speaker.profile.save()

        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="with photo",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=speaker, body="hi",
        )

        self.client.force_login(speaker)
        resp = self.client.get(f"/assistant/support/api/t/{ticket.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        msg = data["messages"][0]
        self.assertIn("sender_avatar_url", msg)
        self.assertTrue(msg["sender_avatar_url"], "expected non-empty avatar URL")

    def test_thread_api_returns_empty_avatar_when_user_has_none(self):
        speaker = _make_user("av_no_photo", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="no photo",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=speaker, body="hi",
        )
        self.client.force_login(speaker)
        resp = self.client.get(f"/assistant/support/api/t/{ticket.id}/")
        self.assertEqual(resp.status_code, 200)
        msg = resp.json()["messages"][0]
        self.assertEqual(msg["sender_avatar_url"], "")

    def test_list_api_includes_preview_and_last_sender(self):
        speaker = _make_user("av_list", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="preview test",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=speaker,
            body="Длинное сообщение для проверки превью списка тикетов",
        )
        self.client.force_login(speaker)
        resp = self.client.get("/assistant/support/api/list/")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["items"]
        self.assertTrue(items)
        item = items[0]
        self.assertIn("last_body_preview", item)
        self.assertTrue(item["last_body_preview"])
        self.assertEqual(item["last_sender_kind"], "user")


class TypingEndpointTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_typing_active_sets_cache_key(self):
        speaker = _make_user("t_speaker", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="typing test",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=speaker, body="x",
        )
        self.client.force_login(speaker)
        resp = self.client.post(
            f"/assistant/support/t/{ticket.id}/typing/",
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(cache.get(f"support:typing:{ticket.id}:user"))

    def test_typing_inactive_clears_cache_key(self):
        speaker = _make_user("t_speaker2", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="typing test 2",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=speaker, body="x",
        )
        self.client.force_login(speaker)
        # Set
        self.client.post(
            f"/assistant/support/t/{ticket.id}/typing/",
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertIsNotNone(cache.get(f"support:typing:{ticket.id}:user"))
        # Clear
        resp = self.client.post(
            f"/assistant/support/t/{ticket.id}/typing/",
            data=json.dumps({"active": False}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(cache.get(f"support:typing:{ticket.id}:user"))

    def test_typing_forbidden_for_non_author_non_admin(self):
        author = _make_user("t_author", "speaker")
        other = _make_user("t_other", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=author, author_kind="user", subject="x",
        )
        SupportMessage.objects.create(
            ticket=ticket, sender_kind="user", sender_user=author, body="x",
        )
        self.client.force_login(other)
        resp = self.client.post(
            f"/assistant/support/t/{ticket.id}/typing/",
            data=json.dumps({"active": True}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


class SupportPagesRemovedTest(TestCase):
    """Support is drawer-only — these page routes must no longer exist."""

    def test_support_home_page_404(self):
        speaker = _make_user("page_gone", "speaker")
        self.client.force_login(speaker)
        resp = self.client.get("/assistant/support/")
        self.assertEqual(resp.status_code, 404)

    def test_support_ticket_page_404(self):
        speaker = _make_user("page_gone2", "speaker")
        ticket = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="x",
        )
        self.client.force_login(speaker)
        resp = self.client.get(f"/assistant/support/t/{ticket.id}/")
        self.assertEqual(resp.status_code, 404)

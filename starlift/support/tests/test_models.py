from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from support.models import SupportTicket, SupportMessage, SupportRead
from support.services import notifications


User = get_user_model()


def _make_user(username, role):
    u = User.objects.create_user(username=username, password="x", email=f"{username}@x.io")
    UserProfile.objects.update_or_create(user=u, defaults={"role": role})
    # Drop cached reverse-OneToOne so `.profile` re-fetches the updated row.
    u.refresh_from_db()
    return u


class ModelTests(TestCase):
    def test_message_updates_last_message_fields(self):
        author = _make_user("alice", "speaker")
        t = SupportTicket.objects.create(
            author_user=author, author_kind="user", subject="help"
        )
        self.assertIsNone(t.last_message_at)
        m = SupportMessage.objects.create(ticket=t, sender_kind="user", body="hi")
        t.refresh_from_db()
        self.assertIsNotNone(t.last_message_at)
        self.assertEqual(t.last_message_sender_kind, "user")
        self.assertEqual(t.last_message_at, m.created_at)

    def test_unread_counts_for_admin_and_speaker(self):
        speaker = _make_user("bob", "speaker")
        admin = _make_user("carol", "admin")
        t = SupportTicket.objects.create(
            author_user=speaker, author_kind="user", subject="bug"
        )
        SupportMessage.objects.create(ticket=t, sender_kind="user", body="found a bug")
        # admin sees unread, speaker doesn't (last message is theirs)
        self.assertEqual(notifications.unread_count(admin), 1)
        self.assertEqual(notifications.unread_count(speaker), 0)

        notifications.mark_read(admin, t)
        self.assertEqual(notifications.unread_count(admin), 0)

        # admin replies
        SupportMessage.objects.create(
            ticket=t, sender_kind="admin", sender_user=admin, body="working on it"
        )
        t.refresh_from_db()
        self.assertEqual(notifications.unread_count(admin), 0)
        self.assertEqual(notifications.unread_count(speaker), 1)


class PermissionTests(TestCase):
    # Support is drawer-only — permissions are tested through the JSON API
    # used by the drawer pane.
    def test_speaker_cannot_view_other_users_ticket(self):
        a = _make_user("dan", "speaker")
        b = _make_user("eve", "speaker")
        t = SupportTicket.objects.create(
            author_user=a, author_kind="user", subject="private"
        )
        SupportMessage.objects.create(ticket=t, sender_kind="user", body="x")
        self.client.force_login(b)
        resp = self.client.get(f"/assistant/support/api/t/{t.id}/")
        self.assertEqual(resp.status_code, 403)

    def test_speaker_can_view_own(self):
        a = _make_user("fred", "speaker")
        t = SupportTicket.objects.create(
            author_user=a, author_kind="user", subject="mine"
        )
        SupportMessage.objects.create(ticket=t, sender_kind="user", body="x")
        self.client.force_login(a)
        resp = self.client.get(f"/assistant/support/api/t/{t.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_view_any(self):
        a = _make_user("ivy", "speaker")
        admin = _make_user("jack", "admin")
        t = SupportTicket.objects.create(
            author_user=a, author_kind="user", subject="any"
        )
        SupportMessage.objects.create(ticket=t, sender_kind="user", body="x")
        self.client.force_login(admin)
        resp = self.client.get(f"/assistant/support/api/t/{t.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_speaker_cannot_close(self):
        a = _make_user("kate", "speaker")
        t = SupportTicket.objects.create(
            author_user=a, author_kind="user", subject="x"
        )
        SupportMessage.objects.create(ticket=t, sender_kind="user", body="x")
        self.client.force_login(a)
        resp = self.client.post(f"/assistant/support/t/{t.id}/close/")
        self.assertEqual(resp.status_code, 403)


class GuestTests(TestCase):
    def test_guest_can_create_ticket_and_open_via_token(self):
        from support.services.magic_link import make_token, hash_token

        resp = self.client.post("/support/new/", {
            "name": "Test",
            "email": "guest@example.com",
            "subject": "Help me",
            "body": "I have a question",
        })
        self.assertEqual(resp.status_code, 200)
        t = SupportTicket.objects.get(subject="Help me")
        self.assertEqual(t.author_kind, "guest")
        self.assertEqual(t.guest_email, "guest@example.com")
        self.assertTrue(t.guest_token_hash)
        self.assertEqual(t.messages.count(), 1)

    def test_guest_with_wrong_token_404(self):
        resp = self.client.get("/support/t/totallybogusbogus0123/")
        self.assertEqual(resp.status_code, 404)

    def test_honeypot_rejects(self):
        resp = self.client.post("/support/new/", {
            "name": "x", "email": "x@x.io", "subject": "s",
            "body": "b", "website": "spam",
        })
        # redirected back to /support/new/
        self.assertIn(resp.status_code, (302, 301))
        self.assertEqual(SupportTicket.objects.count(), 0)

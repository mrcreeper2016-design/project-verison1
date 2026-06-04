"""View-level tests for the support chat (authenticated API + guest flow)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from support.models import SupportTicket
from support.services.magic_link import make_token, hash_token

User = get_user_model()


def _make_user(username, role):
    u = User.objects.create_user(username=username, password="x", email=f"{username}@x.io")
    UserProfile.objects.update_or_create(user=u, defaults={"role": role})
    u.refresh_from_db()
    return u


def _post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


class SupportUserApiTests(TestCase):
    NEW = "/assistant/support/api/new/"
    LIST = "/assistant/support/api/list/"

    def setUp(self):
        self.speaker = _make_user("sp1", "speaker")

    def test_new_api_creates_ticket_with_first_message(self):
        self.client.force_login(self.speaker)
        resp = _post_json(self.client, self.NEW, {"subject": "Help", "body": "It broke"})
        self.assertEqual(resp.status_code, 200)
        ticket = SupportTicket.objects.get(pk=resp.json()["ticket_id"])
        self.assertEqual(ticket.author_user_id, self.speaker.id)
        self.assertEqual(ticket.messages.count(), 1)

    def test_new_api_rejects_empty(self):
        self.client.force_login(self.speaker)
        resp = _post_json(self.client, self.NEW, {"subject": "", "body": ""})
        self.assertEqual(resp.status_code, 400)

    def test_admin_cannot_open_ticket(self):
        self.client.force_login(_make_user("ad1", "admin"))
        resp = _post_json(self.client, self.NEW, {"subject": "x", "body": "y"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "admins_cannot_open")

    def test_thread_api_forbidden_for_other_user(self):
        self.client.force_login(self.speaker)
        tid = _post_json(self.client, self.NEW, {"subject": "s", "body": "b"}).json()["ticket_id"]
        self.client.force_login(_make_user("sp2", "speaker"))
        resp = self.client.get(f"/assistant/support/api/t/{tid}/")
        self.assertEqual(resp.status_code, 403)

    def test_list_api_shows_own_ticket(self):
        self.client.force_login(self.speaker)
        _post_json(self.client, self.NEW, {"subject": "Subj", "body": "Body"})
        resp = self.client.get(self.LIST)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Subj", [it["subject"] for it in resp.json()["items"]])

    def test_list_api_requires_login(self):
        resp = self.client.get(self.LIST)
        self.assertIn(resp.status_code, (302, 403))


class SupportGuestTests(TestCase):
    def test_guest_new_creates_ticket(self):
        resp = self.client.post("/support/new/", data={
            "name": "Guest", "email": "g@example.com",
            "subject": "Question", "body": "How does it work?",
        })
        self.assertEqual(resp.status_code, 200)
        ticket = SupportTicket.objects.get(author_kind=SupportTicket.AUTHOR_GUEST)
        self.assertEqual(ticket.subject, "Question")
        self.assertEqual(ticket.messages.count(), 1)

    def test_guest_send_with_valid_token(self):
        raw = make_token()
        ticket = SupportTicket.objects.create(
            author_kind=SupportTicket.AUTHOR_GUEST,
            guest_email="g@example.com",
            guest_token_hash=hash_token(raw),
            subject="Q",
        )
        resp = _post_json(self.client, f"/support/t/{raw}/send/", {"content": "hello there"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ticket.messages.filter(sender_kind="guest").count(), 1)

    def test_guest_send_invalid_token_404(self):
        resp = _post_json(
            self.client, "/support/t/invalid-token-xxxxxxxx/send/", {"content": "hi"}
        )
        self.assertEqual(resp.status_code, 404)

"""End-to-end tests covering the view layer + agent loop with a fake GigaChat."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from assistant.models import Conversation, Message
from assistant.tests.fakes import FakeGigaChatClient, ScriptedTurn
from starlift.models import Speaker

User = get_user_model()


def _admin_user(username="admin"):
    u = User.objects.create_user(username, password="pw")
    UserProfile.objects.filter(user=u).update(role="admin")
    return User.objects.get(pk=u.pk)


@override_settings(ASSISTANT_RATE_LIMIT_PER_USER=999)
class ChatFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user()
        Speaker.objects.create(name="Anna", stack="Python", nps=90)

    def setUp(self):
        self.client.login(username="admin", password="pw")

    def test_chat_home_creates_or_redirects(self):
        resp = self.client.get(reverse("assistant:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/assistant/c/", resp.url)

    def test_create_conversation_seeds_first_message(self):
        resp = self.client.post(
            reverse("assistant:conversations_create"),
            data=json.dumps({"first_message": "Привет"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        conv_id = resp.json()["conversation_id"]
        self.assertTrue(
            Message.objects.filter(conversation_id=conv_id, role="user", content="Привет").exists()
        )

    def test_chat_detail_renders_thread(self):
        conv = Conversation.objects.create(user=self.user, title="Test")
        Message.objects.create(conversation=conv, role="user", content="Hi there")
        Message.objects.create(conversation=conv, role="assistant", content="Hello!")
        resp = self.client.get(reverse("assistant:chat_detail", args=[conv.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Hi there")
        self.assertContains(resp, "Hello!")

    def test_send_then_stream_records_assistant_reply(self):
        conv = Conversation.objects.create(user=self.user)
        Message.objects.create(conversation=conv, role="user", content="Найди Anna")

        fake = FakeGigaChatClient([
            ScriptedTurn(tool_name="search_speakers", tool_args={"query": "Anna"}),
            ScriptedTurn(text="Нашёл Anna."),
        ])
        with patch("assistant.views.chat.GigaChatClient", return_value=fake):
            resp = self.client.get(reverse("assistant:chat_stream", args=[conv.id]))
            self.assertEqual(resp.status_code, 200)
            body = b"".join(resp.streaming_content).decode("utf-8")

        self.assertIn("event: tool_start", body)
        self.assertIn("event: tool_end", body)
        self.assertIn("event: done", body)
        self.assertTrue(
            Message.objects.filter(
                conversation=conv, role="assistant", content__icontains="Anna"
            ).exists()
        )

    def test_send_message_rejects_empty(self):
        conv = Conversation.objects.create(user=self.user)
        resp = self.client.post(
            reverse("assistant:chat_send", args=[conv.id]),
            data=json.dumps({"content": "   "}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_cannot_access_other_users_conversation(self):
        other = _admin_user("other")
        their_conv = Conversation.objects.create(user=other)
        resp = self.client.get(reverse("assistant:chat_detail", args=[their_conv.id]))
        self.assertEqual(resp.status_code, 404)


class RateLimitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user()

    def setUp(self):
        self.client.login(username="admin", password="pw")
        from django.core.cache import cache
        cache.clear()

    @override_settings(ASSISTANT_RATE_LIMIT_PER_USER=2, ASSISTANT_RATE_LIMIT_WINDOW_SECONDS=900)
    def test_rate_limit_triggers_429(self):
        conv = Conversation.objects.create(user=self.user)
        url = reverse("assistant:chat_send", args=[conv.id])
        body = json.dumps({"content": "msg"})

        ok1 = self.client.post(url, data=body, content_type="application/json")
        ok2 = self.client.post(url, data=body, content_type="application/json")
        blocked = self.client.post(url, data=body, content_type="application/json")
        self.assertEqual(ok1.status_code, 200)
        self.assertEqual(ok2.status_code, 200)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["error"], "rate_limited")

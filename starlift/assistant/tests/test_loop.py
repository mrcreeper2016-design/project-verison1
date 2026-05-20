from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.models import UserProfile
from assistant.agent.loop import AgentEvent, run_turn
from assistant.models import Conversation, Message
from assistant.tests.fakes import FakeGigaChatClient, ScriptedTurn
from starlift.models import Speaker

User = get_user_model()


def _admin_user():
    u = User.objects.create_user("u", password="x")
    UserProfile.objects.filter(user=u).update(role="admin")
    return User.objects.get(pk=u.pk)


class AgentLoopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user()
        Speaker.objects.create(name="Anna", stack="Python", nps=90)

    def test_simple_text_answer(self):
        conv = Conversation.objects.create(user=self.user)
        Message.objects.create(conversation=conv, role="user", content="Привет")
        fake = FakeGigaChatClient([ScriptedTurn(text="Привет! Чем помочь?")])

        events = list(run_turn(conv, client=fake))

        kinds = [e.kind for e in events]
        self.assertEqual(kinds, ["delta", "done"])
        last = Message.objects.filter(conversation=conv).order_by("-id").first()
        self.assertEqual(last.role, "assistant")
        self.assertEqual(last.content, "Привет! Чем помочь?")

    def test_tool_call_then_text(self):
        conv = Conversation.objects.create(user=self.user)
        Message.objects.create(conversation=conv, role="user", content="Найди спикеров")
        fake = FakeGigaChatClient([
            ScriptedTurn(tool_name="search_speakers", tool_args={"query": "Anna"}),
            ScriptedTurn(text="Нашёл одного: Anna."),
        ])

        events = list(run_turn(conv, client=fake))

        kinds = [e.kind for e in events]
        self.assertEqual(kinds, ["tool_start", "tool_end", "delta", "done"])
        tool_msg = Message.objects.filter(conversation=conv, role="tool").first()
        self.assertEqual(tool_msg.tool_name, "search_speakers")
        self.assertIn("Anna", str(tool_msg.tool_result))

    def test_iteration_limit_aborts(self):
        conv = Conversation.objects.create(user=self.user)
        Message.objects.create(conversation=conv, role="user", content="Loop forever")
        fake = FakeGigaChatClient([
            ScriptedTurn(tool_name="search_speakers", tool_args={}) for _ in range(20)
        ])
        with override_settings(ASSISTANT_MAX_TOOL_ITERATIONS=3):
            events = list(run_turn(conv, client=fake))
        self.assertEqual(events[-1].kind, "error")
        self.assertEqual(events[-1].payload["reason"], "max_tools_exceeded")

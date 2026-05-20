from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from assistant.agent.tools import TOOL_REGISTRY
from assistant.agent.tools import events  # noqa: F401
from starlift.models import Event, Speaker

User = get_user_model()


def _admin_user(username="u"):
    """Helper: create user and promote to admin (the signal auto-creates a guest profile)."""
    u = User.objects.create_user(username, password="x")
    UserProfile.objects.filter(user=u).update(role="admin")
    return User.objects.get(pk=u.pk)


class FindEventsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user()
        today = date.today()
        cls.future = Event.objects.create(
            title="Future Conf",
            event_date=today + timedelta(days=10),
            topic="ML",
            status="future",
            location="Moscow",
        )
        cls.past = Event.objects.create(
            title="Old Conf",
            event_date=today - timedelta(days=30),
            topic="DevOps",
            status="past",
        )

    def test_default_returns_future_events(self):
        tool = TOOL_REGISTRY["find_events"]
        result = tool.invoke({}, _user=self.user)
        titles = [e["title"] for e in result["events"]]
        self.assertIn("Future Conf", titles)
        self.assertNotIn("Old Conf", titles)

    def test_topic_filter(self):
        tool = TOOL_REGISTRY["find_events"]
        result = tool.invoke({"topic": "ML"}, _user=self.user)
        titles = [e["title"] for e in result["events"]]
        self.assertEqual(titles, ["Future Conf"])


class GetEventDetailsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user("u2")
        cls.ev = Event.objects.create(
            title="Conf",
            event_date=date.today() + timedelta(days=5),
            description="x" * 1000,
        )
        cls.sp = Speaker.objects.create(name="S1", stack="ML", nps=80)
        cls.ev.speakers.add(cls.sp)

    def test_returns_event_with_speakers(self):
        tool = TOOL_REGISTRY["get_event_details"]
        result = tool.invoke({"event_id": self.ev.id}, _user=self.user)
        self.assertEqual(result["title"], "Conf")
        self.assertLessEqual(len(result["description"]), 500)
        self.assertEqual(result["speakers"], [{"id": self.sp.id, "name": "S1", "nps": 80}])

    def test_missing(self):
        tool = TOOL_REGISTRY["get_event_details"]
        self.assertEqual(tool.invoke({"event_id": 999}, _user=self.user), {"error": "not_found"})

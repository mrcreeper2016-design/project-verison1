from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from assistant.agent.tools import TOOL_REGISTRY
from assistant.agent.tools import speakers  # noqa: F401 — register
from starlift.models import Speaker

User = get_user_model()


class SearchSpeakersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _admin = User.objects.create_user("admin", password="x")
        UserProfile.objects.filter(user=_admin).update(role="admin")
        cls.admin = User.objects.get(pk=_admin.pk)

        _spk = User.objects.create_user("spk", password="x")
        UserProfile.objects.filter(user=_spk).update(role="speaker")
        cls.speaker_user = User.objects.get(pk=_spk.pk)

        cls.s1 = Speaker.objects.create(name="Anna Ivanova", stack="Python ML", nps=85)
        cls.s2 = Speaker.objects.create(name="Boris Petrov", stack="Go DevOps", nps=70)
        cls.s_self = Speaker.objects.create(
            name="Self Speaker", stack="Rust", nps=90, user=cls.speaker_user,
        )

    def test_admin_can_search_all(self):
        tool = TOOL_REGISTRY["search_speakers"]
        result = tool.invoke({"query": "Anna"}, _user=self.admin)
        names = [s["name"] for s in result["speakers"]]
        self.assertIn("Anna Ivanova", names)
        self.assertNotIn("Boris Petrov", names)

    def test_search_filters_by_stack(self):
        tool = TOOL_REGISTRY["search_speakers"]
        result = tool.invoke({"stack": "DevOps"}, _user=self.admin)
        names = [s["name"] for s in result["speakers"]]
        self.assertEqual(names, ["Boris Petrov"])

    def test_search_filters_by_nps_min(self):
        tool = TOOL_REGISTRY["search_speakers"]
        result = tool.invoke({"nps_min": 80}, _user=self.admin)
        names = {s["name"] for s in result["speakers"]}
        self.assertEqual(names, {"Anna Ivanova", "Self Speaker"})

    def test_speaker_sees_only_self(self):
        tool = TOOL_REGISTRY["search_speakers"]
        result = tool.invoke({}, _user=self.speaker_user)
        names = [s["name"] for s in result["speakers"]]
        self.assertEqual(names, ["Self Speaker"])


class GetSpeakerProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _admin = User.objects.create_user("admin2", password="x")
        UserProfile.objects.filter(user=_admin).update(role="admin")
        cls.admin = User.objects.get(pk=_admin.pk)
        cls.s = Speaker.objects.create(name="Anna", stack="Python", bio="long bio " * 100, nps=85)

    def test_returns_profile(self):
        tool = TOOL_REGISTRY["get_speaker_profile"]
        result = tool.invoke({"speaker_id": self.s.id}, _user=self.admin)
        self.assertEqual(result["name"], "Anna")
        self.assertLessEqual(len(result["bio"]), 500)
        self.assertIn("nps", result)

    def test_missing_returns_error_dict(self):
        tool = TOOL_REGISTRY["get_speaker_profile"]
        result = tool.invoke({"speaker_id": 999999}, _user=self.admin)
        self.assertEqual(result, {"error": "not_found"})

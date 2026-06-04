from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserProfile
from assistant.agent.tools import TOOL_REGISTRY
from assistant.agent.tools import analytics  # noqa: F401
from starlift.models import Event, Feedback, Speaker

User = get_user_model()


def _admin_user():
    u = User.objects.create_user("a", password="x")
    UserProfile.objects.filter(user=u).update(role="admin")
    return User.objects.get(pk=u.pk)


class NpsSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _admin_user()
        cls.sp = Speaker.objects.create(name="S")
        cls.ev = Event.objects.create(title="E")
        cls.ev.speakers.add(cls.sp)
        now = timezone.now()
        for score in (10, 10, 9, 6, 3):
            f = Feedback.objects.create(speaker=cls.sp, event=cls.ev, score=score)
            Feedback.objects.filter(pk=f.pk).update(created_at=now - timedelta(days=5))

    def test_summary_counts_promoters_and_detractors(self):
        tool = TOOL_REGISTRY["nps_summary"]
        result = tool.invoke({"period_days": 30}, _user=self.admin)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["promoters"], 3)   # 10, 10, 9
        self.assertEqual(result["detractors"], 2)  # 6, 3
        self.assertAlmostEqual(result["nps"], 20.0, places=1)
        self.assertGreater(result["avg_score"], 0)

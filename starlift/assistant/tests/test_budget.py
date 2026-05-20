from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import UserProfile
from assistant.agent.budget import (
    BudgetExceeded,
    check_conversation_budget,
    check_daily_budget,
    sum_user_tokens_24h,
)
from assistant.models import Conversation, Message

User = get_user_model()


def _admin_user():
    u = User.objects.create_user("u", password="x")
    UserProfile.objects.filter(user=u).update(role="admin")
    return User.objects.get(pk=u.pk)


@override_settings(
    ASSISTANT_MAX_TOKENS_PER_CONVERSATION=100,
    ASSISTANT_DAILY_TOKEN_BUDGET_ADMIN=200,
    ASSISTANT_DAILY_BUDGET_ACTION="block",
)
class BudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = _admin_user()
        cls.conv = Conversation.objects.create(user=cls.user)

    def _msg(self, *, role, t_in=0, t_out=0):
        return Message.objects.create(conversation=self.conv, role=role,
                                       token_in=t_in, token_out=t_out)

    def test_conversation_budget_ok_under_limit(self):
        self._msg(role="assistant", t_in=20, t_out=20)
        check_conversation_budget(self.conv)  # no raise

    def test_conversation_budget_raises_when_exceeded(self):
        self._msg(role="assistant", t_in=80, t_out=40)
        with self.assertRaises(BudgetExceeded) as cm:
            check_conversation_budget(self.conv)
        self.assertEqual(cm.exception.scope, "conversation")

    def test_daily_budget_for_admin(self):
        self._msg(role="assistant", t_in=120, t_out=100)
        self.assertEqual(sum_user_tokens_24h(self.user), 220)
        with self.assertRaises(BudgetExceeded) as cm:
            check_daily_budget(self.user)
        self.assertEqual(cm.exception.scope, "daily")

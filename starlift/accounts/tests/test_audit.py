from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from accounts.models import AuditLog
from accounts.services import audit


User = get_user_model()


class AuditServiceTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.user = User.objects.create_user(username="alice", password="Secret!234")

    def test_log_stores_action_and_actor(self):
        entry = audit.log(action="x.test", actor=self.user, request=self.rf.get("/", REMOTE_ADDR="10.0.0.1"))
        self.assertEqual(entry.action, "x.test")
        self.assertEqual(entry.actor_id, self.user.pk)
        self.assertEqual(entry.ip, "10.0.0.1")

    def test_respects_xff(self):
        req = self.rf.get("/", HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1")
        entry = audit.log(action="x.test", actor=self.user, request=req)
        self.assertEqual(entry.ip, "203.0.113.5")

    def test_target_derived_from_instance(self):
        entry = audit.log(action="x.test", actor=self.user, target=self.user)
        self.assertEqual(entry.target_type, "User")
        self.assertEqual(entry.target_id, str(self.user.pk))

    def test_anonymous_actor_is_none(self):
        entry = audit.log(action="x.test", actor=None)
        self.assertIsNone(entry.actor_id)

    def test_metadata_is_jsonable(self):
        entry = audit.log(action="x.test", metadata={"a": 1, "b": [1, 2]})
        entry.refresh_from_db()
        self.assertEqual(entry.metadata, {"a": 1, "b": [1, 2]})

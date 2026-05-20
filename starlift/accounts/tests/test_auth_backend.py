from django.contrib.auth import authenticate, get_user_model
from django.test import RequestFactory, TestCase


User = get_user_model()


class UsernameOrEmailBackendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="Secret!234",
        )

    def setUp(self):
        self.rf = RequestFactory()

    def _req(self):
        return self.rf.post("/auth/login/")

    def test_login_by_username(self):
        self.assertIsNotNone(authenticate(self._req(), username="alice", password="Secret!234"))

    def test_login_by_email(self):
        self.assertIsNotNone(authenticate(self._req(), username="alice@example.com", password="Secret!234"))

    def test_login_by_email_is_case_insensitive(self):
        self.assertIsNotNone(authenticate(self._req(), username="ALICE@example.COM", password="Secret!234"))

    def test_login_by_username_is_case_insensitive(self):
        self.assertIsNotNone(authenticate(self._req(), username="ALICE", password="Secret!234"))

    def test_wrong_password_returns_none(self):
        self.assertIsNone(authenticate(self._req(), username="alice", password="wrong"))

    def test_unknown_user_returns_none(self):
        self.assertIsNone(authenticate(self._req(), username="bob", password="irrelevant"))

    def test_inactive_user_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertIsNone(authenticate(self._req(), username="alice", password="Secret!234"))

    def test_empty_inputs_return_none(self):
        self.assertIsNone(authenticate(self._req(), username="", password="Secret!234"))
        self.assertIsNone(authenticate(self._req(), username="alice", password=""))

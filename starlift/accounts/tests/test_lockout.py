from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import LoginAttempt
from accounts.services import lockout


@override_settings(ACCOUNTS_LOCKOUT_THRESHOLD=6, ACCOUNTS_LOCKOUT_WINDOW_SECONDS=60)
class LockoutServiceTests(TestCase):
    def test_not_locked_initially(self):
        self.assertFalse(lockout.is_locked("alice"))
        self.assertEqual(lockout.seconds_until_unlock("alice"), 0)

    def test_locks_after_threshold(self):
        for _ in range(5):
            lockout.register_attempt("alice", "127.0.0.1", success=False)
        self.assertFalse(lockout.is_locked("alice"))
        lockout.register_attempt("alice", "127.0.0.1", success=False)
        self.assertTrue(lockout.is_locked("alice"))

    def test_success_clears_failures(self):
        for _ in range(5):
            lockout.register_attempt("alice", "127.0.0.1", success=False)
        lockout.register_attempt("alice", "127.0.0.1", success=True)
        self.assertEqual(
            LoginAttempt.objects.filter(username_or_email="alice", success=False).count(),
            0,
        )
        self.assertFalse(lockout.is_locked("alice"))

    def test_case_insensitive_username(self):
        for _ in range(6):
            lockout.register_attempt("Alice", "127.0.0.1", success=False)
        self.assertTrue(lockout.is_locked("alice"))
        self.assertTrue(lockout.is_locked("ALICE"))

    def test_old_failures_ignored(self):
        past = timezone.now() - timedelta(seconds=120)
        for _ in range(6):
            LoginAttempt.objects.create(username_or_email="alice", success=False, ip="127.0.0.1")
        LoginAttempt.objects.filter(username_or_email="alice").update(created_at=past)
        self.assertFalse(lockout.is_locked("alice"))

    def test_lockout_isolated_per_username(self):
        for _ in range(6):
            lockout.register_attempt("alice", "127.0.0.1", success=False)
        self.assertTrue(lockout.is_locked("alice"))
        self.assertFalse(lockout.is_locked("bob"))

    def test_manual_unlock(self):
        for _ in range(6):
            lockout.register_attempt("alice", "127.0.0.1", success=False)
        self.assertTrue(lockout.is_locked("alice"))
        removed = lockout.unlock("alice")
        self.assertEqual(removed, 6)
        self.assertFalse(lockout.is_locked("alice"))

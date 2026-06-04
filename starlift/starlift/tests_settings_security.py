"""Settings-level security behaviour.

The SECRET_KEY / ALLOWED_HOSTS hardening lives at module import time in
``starlift/settings.py``, so we exercise it by importing settings in a fresh
subprocess with a controlled environment (``ENV_FILE`` pointed at the null
device so the local ``.env`` does not interfere).
"""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

# Directory that contains manage.py (so ``starlift.settings`` is importable).
_BASE_DIR = Path(__file__).resolve().parent.parent
_SETUP = (
    "import django, os; "
    "os.environ['DJANGO_SETTINGS_MODULE'] = 'starlift.settings'; "
    "django.setup()"
)


def _run_settings(env_extra: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ENV_FILE"] = os.devnull  # isolate from the local .env
    env.pop("SECRET_KEY", None)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", _SETUP],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_BASE_DIR),
    )


class SettingsSecurityTests(SimpleTestCase):
    def test_production_without_secret_key_refuses_to_start(self):
        result = _run_settings({"DEBUG": "False", "SECRET_KEY": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_with_secret_key_starts(self):
        result = _run_settings(
            {"DEBUG": "False", "SECRET_KEY": "real-key-123", "ALLOWED_HOSTS": "example.com"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_debug_falls_back_to_insecure_key_with_warning(self):
        result = _run_settings({"DEBUG": "True", "SECRET_KEY": ""})
        self.assertEqual(result.returncode, 0, result.stderr)
        # The insecure-key warning is emitted on stderr but must not be fatal.
        self.assertIn("SECRET_KEY", result.stderr)

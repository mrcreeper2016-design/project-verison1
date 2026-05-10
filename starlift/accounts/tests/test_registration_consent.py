from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Invite, UserProfile
from accounts.services import tokens as token_svc

User = get_user_model()


VALID_PAYLOAD = {
    "username": "newuser",
    "first_name": "Иван",
    "last_name": "Петров",
    "email": "newuser@example.com",
    "password1": "ComplexPass!234",
    "password2": "ComplexPass!234",
    "consent_pdn": "on",
    "accept_policy": "on",
}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationConsentTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:register")

    def test_register_without_consent_pdn_fails(self):
        payload = {**VALID_PAYLOAD}
        payload.pop("consent_pdn")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_register_without_accept_policy_fails(self):
        payload = {**VALID_PAYLOAD}
        payload.pop("accept_policy")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_register_with_consent_records_consent(self):
        response = self.client.post(self.url, VALID_PAYLOAD)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newuser")
        profile = user.profile
        self.assertIsNotNone(profile.pdn_consent_at)
        self.assertIsNotNone(profile.policy_accepted_at)
        self.assertEqual(profile.consent_doc_version, settings.LEGAL_DOC_VERSION)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=user, action=AuditLog.ACTION_CONSENT_GIVEN
            ).exists()
        )


class InviteConsentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="x", email="a@example.com"
        )
        self.raw = token_svc.make_token()
        self.invite = Invite.objects.create(
            email="invitee@example.com",
            role=UserProfile.ROLE_SPEAKER,
            created_by=self.admin,
            token_hash=token_svc.hash_token(self.raw),
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.url = reverse("accounts:invite_accept", args=[self.raw])

    def _payload(self, **overrides):
        base = {
            "username": "invitee",
            "first_name": "Anna",
            "last_name": "S",
            "password1": "ComplexPass!234",
            "password2": "ComplexPass!234",
            "consent_pdn": "on",
            "accept_policy": "on",
        }
        base.update(overrides)
        return base

    def test_invite_without_consent_fails(self):
        payload = self._payload()
        payload.pop("consent_pdn")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="invitee").exists())

    def test_invite_with_consent_records_consent(self):
        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="invitee")
        profile = user.profile
        self.assertIsNotNone(profile.pdn_consent_at)
        self.assertIsNotNone(profile.policy_accepted_at)
        self.assertEqual(profile.consent_doc_version, settings.LEGAL_DOC_VERSION)
        self.assertTrue(
            AuditLog.objects.filter(
                actor=user, action=AuditLog.ACTION_CONSENT_GIVEN
            ).exists()
        )


class ConsentSchemaTests(TestCase):
    def test_userprofile_has_consent_fields(self):
        user = User.objects.create_user(
            username="legacy", password="x", email="l@example.com"
        )
        self.assertTrue(hasattr(user.profile, "pdn_consent_at"))
        self.assertTrue(hasattr(user.profile, "policy_accepted_at"))
        self.assertTrue(hasattr(user.profile, "consent_doc_version"))

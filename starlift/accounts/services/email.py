"""Thin wrappers around Django's send_mail for auth-related notifications.

Using dedicated functions here lets tests easily patch these call-sites
without touching every view.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse


def _site_url() -> str:
    return getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")


def _send(to: str, subject: str, body_text: str, body_html: str | None = None) -> int:
    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    if body_html:
        msg.attach_alternative(body_html, "text/html")
    return msg.send(fail_silently=False)


def send_invite_email(*, to: str, raw_token: str, role: str, inviter_name: str = "") -> int:
    link = f"{_site_url()}{reverse('accounts:invite_accept', args=[raw_token])}"
    ctx = {
        "link": link,
        "role": role,
        "inviter_name": inviter_name,
        "site_name": getattr(settings, "SITE_NAME", "StarLift"),
    }
    subject = "Приглашение в StarLift"
    text = render_to_string("accounts/emails/invite.txt", ctx)
    html = render_to_string("accounts/emails/invite.html", ctx)
    return _send(to, subject, text, html)


def send_email_change_verification(*, to: str, raw_token: str, username: str) -> int:
    link = f"{_site_url()}{reverse('accounts:verify_email', args=[raw_token])}"
    ctx = {
        "link": link,
        "username": username,
        "site_name": getattr(settings, "SITE_NAME", "StarLift"),
    }
    subject = "Подтверждение нового email в StarLift"
    text = render_to_string("accounts/emails/verify_email.txt", ctx)
    html = render_to_string("accounts/emails/verify_email.html", ctx)
    return _send(to, subject, text, html)


def send_registration_verification(*, to: str, raw_token: str, username: str) -> int:
    """Verification email for self-service registration (guest accounts).

    Uses a dedicated template with registration-specific wording to avoid
    confusing the user with "change your email" copy when they just signed up.
    """
    link = f"{_site_url()}{reverse('accounts:verify_email', args=[raw_token])}"
    ctx = {
        "link": link,
        "username": username,
        "site_name": getattr(settings, "SITE_NAME", "StarLift"),
    }
    subject = "Подтверждение регистрации в StarLift"
    text = render_to_string("accounts/emails/register_verify.txt", ctx)
    html = render_to_string("accounts/emails/register_verify.html", ctx)
    return _send(to, subject, text, html)

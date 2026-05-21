"""Email to the guest with their magic-link, and admin reply notifications."""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


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
    return msg.send(fail_silently=True)


def send_guest_link(*, to: str, raw_token: str, subject_line: str) -> int:
    link = f"{_site_url()}/support/t/{raw_token}/"
    ctx = {
        "link": link,
        "subject_line": subject_line,
        "site_name": getattr(settings, "SITE_NAME", "StarLift"),
    }
    text = render_to_string("support/emails/guest_link.txt", ctx)
    html = render_to_string("support/emails/guest_link.html", ctx)
    return _send(to, "Ваше обращение в поддержку StarLift", text, html)


def send_guest_first_reply(*, to: str, raw_token: str, subject_line: str) -> int:
    """Notify guest that support has replied for the first time."""
    link = f"{_site_url()}/support/t/{raw_token}/"
    ctx = {
        "link": link,
        "subject_line": subject_line,
        "site_name": getattr(settings, "SITE_NAME", "StarLift"),
    }
    text = render_to_string("support/emails/guest_reply.txt", ctx)
    html = render_to_string("support/emails/guest_reply.html", ctx)
    return _send(to, "Ответ поддержки StarLift", text, html)

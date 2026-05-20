"""Password reset (forgot-password) and password change.

Built on top of Django's class-based auth views — we only swap the form
classes, template paths, and hook into our audit log.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    PasswordChangeDoneView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator

from ..forms import StarliftPasswordChangeForm, StarliftPasswordResetForm, StarliftSetPasswordForm
from ..models import AuditLog
from ..services import audit


class StarliftPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/emails/password_reset.txt"
    html_email_template_name = "accounts/emails/password_reset.html"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    form_class = StarliftPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")

    def form_valid(self, form):
        email = form.cleaned_data.get("email", "").strip().lower()

        # Simple per-email throttle using the latest audit entry.
        interval = getattr(settings, "ACCOUNTS_RESET_EMAIL_MIN_INTERVAL_SECONDS", 300)
        recent = (
            AuditLog.objects
            .filter(action=AuditLog.ACTION_PASSWORD_RESET_REQUESTED, target_id=email[:64])
            .order_by("-created_at")
            .first()
        )
        if recent and (timezone.now() - recent.created_at).total_seconds() < interval:
            # Silently redirect to the done-page to avoid leaking whether an
            # account exists. The user still gets the same UX.
            return super(PasswordResetView, self).form_valid(form)

        response = super().form_valid(form)
        User = get_user_model()
        actor = User.objects.filter(email__iexact=email).first()
        audit.log(
            action=AuditLog.ACTION_PASSWORD_RESET_REQUESTED,
            actor=actor,
            request=self.request,
            target_type="Email",
            target_id=email[:64],
        )
        return response


class StarliftPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class StarliftPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = StarliftSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        audit.log(
            action=AuditLog.ACTION_PASSWORD_RESET_COMPLETED,
            actor=user,
            request=self.request,
            target=user,
        )
        return response


class StarliftPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


@method_decorator(login_required, name="dispatch")
class StarliftPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StarliftPasswordChangeForm
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(
            action=AuditLog.ACTION_PASSWORD_CHANGED,
            actor=self.request.user,
            request=self.request,
            target=self.request.user,
        )
        return response


@method_decorator(login_required, name="dispatch")
class StarliftPasswordChangeDoneView(PasswordChangeDoneView):
    template_name = "accounts/password_change_done.html"

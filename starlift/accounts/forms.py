from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import (
    PasswordChangeForm as DjangoPasswordChangeForm,
    PasswordResetForm as DjangoPasswordResetForm,
    SetPasswordForm as DjangoSetPasswordForm,
)
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import Invite, UserProfile


User = get_user_model()


_INPUT_CLASS = "input-compact"
_INPUT_STYLE = "width:100%"


def _field_attrs(extra: str = "", placeholder: str = "") -> dict:
    attrs = {
        "class": f"{_INPUT_CLASS} {extra}".strip(),
        "style": _INPUT_STYLE,
        "autocomplete": "off",
    }
    if placeholder:
        attrs["placeholder"] = placeholder
    return attrs


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Имя пользователя или email",
        max_length=254,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="username или you@example.com")),
    )
    password = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs(placeholder="••••••••")),
    )


class InviteCreateForm(forms.ModelForm):
    send_email = forms.BooleanField(required=False, initial=True, label="Отправить письмо с приглашением")

    class Meta:
        model = Invite
        fields = ["email", "role", "speaker"]
        widgets = {
            "email": forms.EmailInput(attrs=_field_attrs(placeholder="speaker@example.com")),
            "role": forms.Select(attrs={"class": "select-compact"}),
            "speaker": forms.Select(attrs={"class": "select-compact"}),
        }

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError("Укажите email")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Пользователь с таким email уже зарегистрирован")
        active_exists = Invite.objects.filter(
            email__iexact=email, used_at__isnull=True, revoked_at__isnull=True
        ).exists()
        if active_exists:
            raise ValidationError("Активный инвайт на этот email уже существует")
        return email


class RegisterForm(forms.Form):
    """Open self-service registration — creates a `guest` account pending verification."""

    username = forms.CharField(
        label="Имя пользователя",
        min_length=3,
        max_length=150,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="username")),
    )
    first_name = forms.CharField(
        label="Имя",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    last_name = forms.CharField(
        label="Фамилия",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs=_field_attrs(placeholder="you@example.com")),
    )
    password1 = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs()),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs()),
    )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise ValidationError("Укажите имя пользователя")
        if "@" in username:
            raise ValidationError("Имя пользователя не может содержать @")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Такое имя пользователя уже занято")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError("Укажите email")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("Пользователь с таким email уже зарегистрирован")
        # Also reject if there's an active invite on this email — the user
        # should accept the invite instead of registering a parallel account.
        if Invite.objects.filter(
            email__iexact=email, used_at__isnull=True, revoked_at__isnull=True
        ).exists():
            raise ValidationError(
                "На этот email выслано приглашение. Используйте ссылку из письма."
            )
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Пароли не совпадают")
        if p1:
            fake_user = User(
                username=cleaned.get("username") or "",
                email=cleaned.get("email") or "",
                first_name=cleaned.get("first_name") or "",
                last_name=cleaned.get("last_name") or "",
            )
            try:
                password_validation.validate_password(p1, fake_user)
            except ValidationError as e:
                self.add_error("password1", e)
        return cleaned


class InviteSignupForm(forms.Form):
    username = forms.CharField(
        label="Имя пользователя",
        min_length=3,
        max_length=150,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="username")),
    )
    first_name = forms.CharField(
        label="Имя",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    last_name = forms.CharField(
        label="Фамилия",
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    password1 = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs()),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs()),
    )

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not username:
            raise ValidationError("Укажите имя пользователя")
        if "@" in username:
            raise ValidationError("Имя пользователя не может содержать @")
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("Такое имя пользователя уже занято")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Пароли не совпадают")
        if p1:
            fake_user = User(
                username=cleaned.get("username") or "",
                first_name=cleaned.get("first_name") or "",
                last_name=cleaned.get("last_name") or "",
            )
            try:
                password_validation.validate_password(p1, fake_user)
            except ValidationError as e:
                self.add_error("password1", e)
        return cleaned


class ProfileEditForm(forms.Form):
    first_name = forms.CharField(label="Имя", max_length=150, required=False, widget=forms.TextInput(attrs=_field_attrs()))
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False, widget=forms.TextInput(attrs=_field_attrs()))
    bio = forms.CharField(
        label="О себе",
        required=False,
        widget=forms.Textarea(attrs={**_field_attrs(), "rows": 4, "style": "width:100%; min-height:120px;"}),
    )


class SpeakerProfileForm(forms.Form):
    """Speaker-owned fields for the linked `starlift.Speaker` card.

    Name and bio are not exposed here because they are synced from the
    account profile (`first_name`, `last_name`, `bio`).
    """

    sub = forms.CharField(
        label="Подзаголовок",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    stack = forms.CharField(
        label="Стек",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="Python, Django, ML")),
    )
    city = forms.CharField(
        label="Город",
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs()),
    )
    status = forms.CharField(
        label="Статус",
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="Активен")),
    )


class EmailChangeForm(forms.Form):
    new_email = forms.EmailField(label="Новый email", widget=forms.EmailInput(attrs=_field_attrs(placeholder="you@example.com")))
    current_password = forms.CharField(
        label="Текущий пароль",
        strip=False,
        widget=forms.PasswordInput(attrs=_field_attrs()),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_new_email(self):
        email = (self.cleaned_data.get("new_email") or "").strip().lower()
        if email == (self.user.email or "").lower():
            raise ValidationError("Новый email совпадает с текущим")
        if User.objects.filter(Q(email__iexact=email) & ~Q(pk=self.user.pk)).exists():
            raise ValidationError("Этот email уже используется")
        return email

    def clean_current_password(self):
        password = self.cleaned_data.get("current_password")
        if not self.user.check_password(password):
            raise ValidationError("Неверный пароль")
        return password


class StarliftPasswordChangeForm(DjangoPasswordChangeForm):
    """Styled password-change form; validation from Django + our policy."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("old_password", "new_password1", "new_password2"):
            self.fields[field].widget.attrs.update(_field_attrs())
            self.fields[field].strip = False


class StarliftPasswordResetForm(DjangoPasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(_field_attrs(placeholder="you@example.com"))


class StarliftSetPasswordForm(DjangoSetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("new_password1", "new_password2"):
            self.fields[field].widget.attrs.update(_field_attrs())
            self.fields[field].strip = False

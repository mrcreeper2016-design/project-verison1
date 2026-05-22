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
from django.utils.safestring import mark_safe

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


def _email_field_attrs(placeholder: str = "", autocomplete: str = "email") -> dict:
    # Mobile keyboards (особенно iOS) по умолчанию обрабатывают input как предложение:
    # автокапитализация и «умная» пунктуация после точки вставляют пробел.
    # Эти атрибуты выключают авто-исправления и переводят клавиатуру в email-режим.
    attrs = _field_attrs(placeholder=placeholder)
    attrs.update({
        "autocomplete": autocomplete,
        "autocapitalize": "none",
        "autocorrect": "off",
        "spellcheck": "false",
        "inputmode": "email",
    })
    return attrs


_CONSENT_PDN_LABEL = mark_safe(
    'Я даю согласие на обработку моих персональных данных в соответствии с '
    '<button type="button" class="legal-link" data-legal="consent">'
    'Согласием на обработку ПДн</button> и ФЗ-152.'
)
_ACCEPT_POLICY_LABEL = mark_safe(
    'Я ознакомлен и принимаю '
    '<button type="button" class="legal-link" data-legal="privacy">'
    'Политику конфиденциальности</button> и '
    '<button type="button" class="legal-link" data-legal="terms">'
    'Пользовательское соглашение</button>.'
)
_CONSENT_PDN_REQUIRED_MSG = "Для регистрации необходимо согласие на обработку персональных данных."
_ACCEPT_POLICY_REQUIRED_MSG = "Необходимо принять Политику конфиденциальности и Пользовательское соглашение."


class LoginForm(forms.Form):
    username = forms.CharField(
        label="Имя пользователя или email",
        max_length=254,
        widget=forms.TextInput(attrs=_email_field_attrs(
            placeholder="username или you@example.com",
            autocomplete="username",
        )),
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
            "email": forms.EmailInput(attrs=_email_field_attrs(placeholder="speaker@example.com")),
            "role": forms.Select(attrs={"class": "select-compact"}),
            "speaker": forms.Select(attrs={"class": "select-compact"}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._actor = actor
        # DevRel may invite only speakers/guests; admin may invite any role.
        if actor is not None and not actor.is_superuser:
            profile = getattr(actor, "profile", None)
            if profile is not None and profile.role == UserProfile.ROLE_DEVREL:
                self.fields["role"].choices = [
                    (UserProfile.ROLE_SPEAKER, "Спикер"),
                    (UserProfile.ROLE_GUEST, "Гость"),
                ]

    def clean_role(self):
        role = self.cleaned_data.get("role")
        actor = getattr(self, "_actor", None)
        if actor is not None and not actor.is_superuser:
            profile = getattr(actor, "profile", None)
            if profile is not None and profile.role == UserProfile.ROLE_DEVREL:
                if role not in (UserProfile.ROLE_SPEAKER, UserProfile.ROLE_GUEST):
                    raise ValidationError("DevRel может приглашать только спикеров и гостей.")
        return role

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
        widget=forms.EmailInput(attrs=_email_field_attrs(placeholder="you@example.com")),
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
    consent_pdn = forms.BooleanField(
        required=True,
        label=_CONSENT_PDN_LABEL,
        error_messages={"required": _CONSENT_PDN_REQUIRED_MSG},
    )
    accept_policy = forms.BooleanField(
        required=True,
        label=_ACCEPT_POLICY_LABEL,
        error_messages={"required": _ACCEPT_POLICY_REQUIRED_MSG},
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
    consent_pdn = forms.BooleanField(
        required=True,
        label=_CONSENT_PDN_LABEL,
        error_messages={"required": _CONSENT_PDN_REQUIRED_MSG},
    )
    accept_policy = forms.BooleanField(
        required=True,
        label=_ACCEPT_POLICY_LABEL,
        error_messages={"required": _ACCEPT_POLICY_REQUIRED_MSG},
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
    avatar = forms.ImageField(
        label="Аватар",
        required=False,
        widget=forms.FileInput(attrs={
            "class": "avatar-file-input",
            "accept": "image/jpeg,image/png,image/webp",
        }),
    )
    company = forms.CharField(
        label="Компания",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={**_field_attrs(placeholder="Сбербанк, Тинькофф..."), "list": "company-suggestions", "autocomplete": "off"}),
    )
    bio = forms.CharField(
        label="О себе",
        required=False,
        widget=forms.Textarea(attrs={**_field_attrs(), "rows": 4, "style": "width:100%; min-height:120px;"}),
    )

    def clean_company(self):
        return (self.cleaned_data.get("company") or "").strip()

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        if avatar.size > 10 * 1024 * 1024:
            raise ValidationError("Размер файла не должен превышать 10 МБ.")
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if avatar.content_type not in allowed_types:
            raise ValidationError("Допустимые форматы: JPEG, PNG, WebP.")
        return avatar


class SpeakerProfileMainForm(forms.Form):
    """Единое «Основное» для спикера с привязанной карточкой: имя, аватар, компания, описание (`Speaker.stack`)."""

    first_name = forms.CharField(label="Имя", max_length=150, required=False, widget=forms.TextInput(attrs=_field_attrs()))
    last_name = forms.CharField(label="Фамилия", max_length=150, required=False, widget=forms.TextInput(attrs=_field_attrs()))
    avatar = forms.ImageField(
        label="Аватар",
        required=False,
        widget=forms.FileInput(attrs={
            "class": "avatar-file-input",
            "accept": "image/jpeg,image/png,image/webp,image/gif",
        }),
    )
    company = forms.CharField(
        label="Компания",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={**_field_attrs(placeholder="Сбербанк, СберТех..."), "list": "company-suggestions", "autocomplete": "off"}),
    )
    description = forms.CharField(
        label="Описание",
        max_length=200,
        required=False,
        widget=forms.Textarea(attrs={**_field_attrs(), "rows": 4, "style": "width:100%; min-height:120px;"}),
    )

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        if avatar.size > 10 * 1024 * 1024:
            raise ValidationError("Размер файла не должен превышать 10 МБ.")
        allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        if avatar.content_type not in allowed_types:
            raise ValidationError("Допустимые форматы: JPEG, PNG, GIF, WebP.")
        return avatar


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


class SpeakerApplicationForm(forms.Form):
    """Форма заявки на статус спикера, заполняется гостем после email-верификации."""

    company = forms.CharField(
        label="Компания",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={**_field_attrs(placeholder="Сбербанк, СберТех... (опционально)"), "list": "company-suggestions", "autocomplete": "off"}),
    )
    city = forms.CharField(
        label="Город",
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="Москва")),
    )
    stack = forms.CharField(
        label="Стек / темы",
        max_length=200,
        required=True,
        widget=forms.TextInput(attrs=_field_attrs(placeholder="Python, Django, ML")),
    )
    description = forms.CharField(
        label="О себе",
        required=True,
        widget=forms.Textarea(attrs={**_field_attrs(placeholder="Чем занимаетесь, опыт выступлений, темы..."), "rows": 5, "style": "width:100%; min-height:140px;"}),
    )
    avatar = forms.ImageField(
        label="Аватар",
        required=False,
        widget=forms.FileInput(attrs={
            "class": "avatar-file-input",
            "accept": "image/jpeg,image/png,image/webp",
        }),
    )

    def clean_company(self):
        return (self.cleaned_data.get("company") or "").strip()

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if not avatar:
            return avatar
        if avatar.size > 10 * 1024 * 1024:
            raise ValidationError("Размер файла не должен превышать 10 МБ.")
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        if avatar.content_type not in allowed_types:
            raise ValidationError("Допустимые форматы: JPEG, PNG, WebP.")
        return avatar


class EmailChangeForm(forms.Form):
    new_email = forms.EmailField(label="Новый email", widget=forms.EmailInput(attrs=_email_field_attrs(placeholder="you@example.com")))
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
        self.fields["email"].widget.attrs.update(_email_field_attrs(placeholder="you@example.com"))


class StarliftSetPasswordForm(DjangoSetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ("new_password1", "new_password2"):
            self.fields[field].widget.attrs.update(_field_attrs())
            self.fields[field].strip = False

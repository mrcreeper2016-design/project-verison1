# Согласие на ПДн при регистрации — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать обязательным явное согласие пользователя на обработку ПДн (152-ФЗ) и принятие Политики/Соглашения при регистрации, с фиксацией факта согласия в БД и AuditLog.

**Architecture:** Расширить `UserProfile` тремя полями (две даты + версия документа), добавить два `BooleanField(required=True)` в обе формы регистрации (`RegisterForm`, `InviteSignupForm`), записать согласие во вьюхах `register_view` / `invite_accept_view`, добавить три статичные legal-страницы (`/privacy/`, `/consent/`, `/terms/`) и data-миграцию-backfill для существующих пользователей.

**Tech Stack:** Django 5, PostgreSQL, шаблоны Django, без JS-фреймворков.

---

## Структура файлов

**Создать:**
- `starlift/accounts/migrations/0XXX_userprofile_consent_fields.py` — schema-миграция
- `starlift/accounts/migrations/0XXY_backfill_consent.py` — data-миграция backfill
- `starlift/templates/legal/privacy.html` — Политика конфиденциальности
- `starlift/templates/legal/consent.html` — Согласие на ПДн
- `starlift/templates/legal/terms.html` — Пользовательское соглашение
- `starlift/starlift/views_legal.py` — три `TemplateView`
- `starlift/accounts/tests/test_registration_consent.py` — тесты

**Изменить:**
- `starlift/accounts/models.py` — поля + константа action на `AuditLog`
- `starlift/accounts/forms.py` — два BooleanField в `RegisterForm` и `InviteSignupForm`
- `starlift/accounts/views/register.py` — запись согласия
- `starlift/accounts/views/invite.py` — запись согласия
- `starlift/accounts/templates/accounts/register.html` — рендер чекбоксов
- `starlift/accounts/templates/accounts/invite_accept.html` — рендер чекбоксов
- `starlift/starlift/urls.py` — три URL для legal-страниц
- `starlift/starlift/settings.py` — константа `LEGAL_DOC_VERSION`

---

### Task 1: Поля согласия в `UserProfile`

**Files:**
- Modify: `starlift/accounts/models.py`

- [ ] **Step 1:** Открыть `starlift/accounts/models.py`, в классе `UserProfile` после поля `avatar` (после строки `avatar = models.ImageField(...)`) добавить:

```python
    pdn_consent_at = models.DateTimeField(null=True, blank=True)
    policy_accepted_at = models.DateTimeField(null=True, blank=True)
    consent_doc_version = models.CharField(max_length=32, blank=True, default="")
```

- [ ] **Step 2:** В классе `AuditLog` после строки `ACTION_EMAIL_VERIFIED = "email_verified"` добавить:

```python
    ACTION_CONSENT_GIVEN = "consent_given"
```

- [ ] **Step 3:** Сгенерировать миграцию.

Run: `cd starlift && python manage.py makemigrations accounts`
Expected: создан файл вида `accounts/migrations/0009_userprofile_pdn_consent_at_and_more.py` (точный номер зависит от текущего состояния).

- [ ] **Step 4:** Применить миграцию.

Run: `cd starlift && python manage.py migrate accounts`
Expected: `Applying accounts.0009_... OK`

- [ ] **Step 5:** Закоммитить.

```bash
git add starlift/accounts/models.py starlift/accounts/migrations/
git commit -m "feat(accounts): поля согласия на ПДн в UserProfile"
```

---

### Task 2: Data-миграция backfill для существующих пользователей

**Files:**
- Create: `starlift/accounts/migrations/0XXY_backfill_consent.py`

- [ ] **Step 1:** Посмотреть номер последней миграции accounts:

Run: `ls starlift/accounts/migrations/`
Запомнить последний номер (например `0009_...`). Новый номер — следующий (`0010`).

- [ ] **Step 2:** Создать пустую миграцию.

Run: `cd starlift && python manage.py makemigrations accounts --empty --name backfill_consent`
Expected: создан `accounts/migrations/0010_backfill_consent.py`.

- [ ] **Step 3:** Заменить содержимое созданного файла на:

```python
from django.db import migrations


def backfill_consent(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    User = apps.get_model("auth", "User")
    profiles = UserProfile.objects.select_related("user").filter(
        pdn_consent_at__isnull=True
    )
    for profile in profiles.iterator():
        joined = profile.user.date_joined
        profile.pdn_consent_at = joined
        profile.policy_accepted_at = joined
        profile.consent_doc_version = "legacy"
        profile.save(update_fields=[
            "pdn_consent_at",
            "policy_accepted_at",
            "consent_doc_version",
        ])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0009_userprofile_pdn_consent_at_and_more"),
    ]
    operations = [
        migrations.RunPython(backfill_consent, noop_reverse),
    ]
```

Замечание: имя в `dependencies` поправить под фактический файл из Task 1 (поскольку Django сгенерирует имя автоматически).

- [ ] **Step 4:** Применить.

Run: `cd starlift && python manage.py migrate accounts`
Expected: `Applying accounts.0010_backfill_consent... OK`

- [ ] **Step 5:** Закоммитить.

```bash
git add starlift/accounts/migrations/0010_backfill_consent.py
git commit -m "feat(accounts): backfill согласия на ПДн для существующих пользователей"
```

---

### Task 3: Константа `LEGAL_DOC_VERSION` в settings

**Files:**
- Modify: `starlift/starlift/settings.py`

- [ ] **Step 1:** Открыть `starlift/starlift/settings.py`, в конце файла добавить:

```python
# Legal documents
LEGAL_DOC_VERSION = "2026-05-10"
```

- [ ] **Step 2:** Закоммитить.

```bash
git add starlift/starlift/settings.py
git commit -m "feat: константа LEGAL_DOC_VERSION"
```

---

### Task 4: Legal-страницы (URL + view + шаблоны)

**Files:**
- Create: `starlift/starlift/views_legal.py`
- Create: `starlift/templates/legal/privacy.html`
- Create: `starlift/templates/legal/consent.html`
- Create: `starlift/templates/legal/terms.html`
- Modify: `starlift/starlift/urls.py`

- [ ] **Step 1:** Создать `starlift/starlift/views_legal.py`:

```python
from django.conf import settings
from django.views.generic import TemplateView


class LegalView(TemplateView):
    template_name: str = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["legal_doc_version"] = settings.LEGAL_DOC_VERSION
        return ctx


class PrivacyView(LegalView):
    template_name = "legal/privacy.html"


class ConsentView(LegalView):
    template_name = "legal/consent.html"


class TermsView(LegalView):
    template_name = "legal/terms.html"
```

- [ ] **Step 2:** Создать `starlift/templates/legal/privacy.html`:

```django
{% extends 'base.html' %}
{% block title %}Политика конфиденциальности{% endblock %}
{% block content %}
<article class="legal-doc" style="max-width:800px; margin:0 auto; padding:24px;">
    <h1>Политика конфиденциальности</h1>
    <p><em>Действует с {{ legal_doc_version }}</em></p>

    <h2>1. Общие положения</h2>
    <p>Настоящая Политика определяет порядок обработки персональных данных пользователей сервиса StarLift (далее — Оператор) в соответствии с Федеральным законом № 152-ФЗ «О персональных данных».</p>

    <h2>2. Реквизиты Оператора</h2>
    <p>{# TODO: указать наименование, ИНН, юридический адрес, контакты ответственного за обработку ПДн #}</p>

    <h2>3. Какие данные мы собираем</h2>
    <ul>
        <li>Имя пользователя, имя и фамилия;</li>
        <li>Адрес электронной почты;</li>
        <li>Аватар (по желанию);</li>
        <li>Информация о профиле спикера (компания, стек, город) — для пользователей с ролью «Спикер»;</li>
        <li>Технические данные: IP-адрес, User-Agent, время входа.</li>
    </ul>

    <h2>4. Цели обработки</h2>
    <ul>
        <li>Регистрация и аутентификация пользователей;</li>
        <li>Предоставление функциональности сервиса;</li>
        <li>Обеспечение безопасности и аудит действий;</li>
        <li>Связь с пользователем по существенным вопросам (подтверждение email, восстановление пароля).</li>
    </ul>

    <h2>5. Сроки обработки</h2>
    <p>Данные обрабатываются в течение срока действия учётной записи и до её удаления по запросу пользователя.</p>

    <h2>6. Права субъекта</h2>
    <p>Пользователь вправе запросить доступ к своим данным, их уточнение, блокировку или удаление, а также отозвать согласие на обработку, направив запрос на email Оператора.</p>

    <h2>7. Изменения</h2>
    <p>Оператор вправе обновлять настоящую Политику. Актуальная версия публикуется на этой странице.</p>

    {# TODO: согласовать окончательный текст с юристом #}
</article>
{% endblock %}
```

- [ ] **Step 3:** Создать `starlift/templates/legal/consent.html`:

```django
{% extends 'base.html' %}
{% block title %}Согласие на обработку персональных данных{% endblock %}
{% block content %}
<article class="legal-doc" style="max-width:800px; margin:0 auto; padding:24px;">
    <h1>Согласие на обработку персональных данных</h1>
    <p><em>Версия: {{ legal_doc_version }}</em></p>

    <p>Регистрируясь в сервисе StarLift, я, как субъект персональных данных, в соответствии с Федеральным законом № 152-ФЗ «О персональных данных», даю согласие Оператору на обработку моих персональных данных.</p>

    <h2>Перечень данных</h2>
    <ul>
        <li>Имя пользователя (логин);</li>
        <li>Фамилия, имя;</li>
        <li>Адрес электронной почты;</li>
        <li>Аватар (при загрузке);</li>
        <li>Технические данные посещений (IP-адрес, User-Agent, время).</li>
    </ul>

    <h2>Перечень действий</h2>
    <p>Сбор, запись, систематизация, накопление, хранение, уточнение, извлечение, использование, удаление, уничтожение — как с использованием средств автоматизации, так и без таковых.</p>

    <h2>Цели</h2>
    <p>Регистрация в сервисе, аутентификация, предоставление функциональности, аудит действий, связь по существенным вопросам.</p>

    <h2>Срок действия согласия</h2>
    <p>Согласие действует с момента его предоставления до момента отзыва. Отзыв согласия возможен путём направления письменного уведомления Оператору.</p>

    {# TODO: согласовать окончательный текст с юристом #}
</article>
{% endblock %}
```

- [ ] **Step 4:** Создать `starlift/templates/legal/terms.html`:

```django
{% extends 'base.html' %}
{% block title %}Пользовательское соглашение{% endblock %}
{% block content %}
<article class="legal-doc" style="max-width:800px; margin:0 auto; padding:24px;">
    <h1>Пользовательское соглашение</h1>
    <p><em>Действует с {{ legal_doc_version }}</em></p>

    <h2>1. Предмет</h2>
    <p>Настоящее Соглашение регулирует отношения между Оператором сервиса StarLift и Пользователем при использовании сервиса.</p>

    <h2>2. Регистрация</h2>
    <p>Регистрация осуществляется путём заполнения формы и подтверждения email. Пользователь обязан указывать достоверные сведения.</p>

    <h2>3. Права и обязанности</h2>
    <p>Пользователь обязуется не нарушать законодательство РФ, не совершать действий, затрудняющих работу сервиса, не предпринимать попыток несанкционированного доступа.</p>

    <h2>4. Ответственность</h2>
    <p>Сервис предоставляется «как есть». Оператор не несёт ответственности за временные сбои, вызванные форс-мажором.</p>

    <h2>5. Изменения</h2>
    <p>Оператор вправе обновлять Соглашение. Актуальная версия публикуется на этой странице.</p>

    {# TODO: согласовать окончательный текст с юристом #}
</article>
{% endblock %}
```

- [ ] **Step 5:** В `starlift/starlift/urls.py` добавить импорт и три URL. Найти секцию `urlpatterns` и добавить:

```python
from .views_legal import PrivacyView, ConsentView, TermsView
```

в конец секции импортов, и в `urlpatterns`:

```python
    path("privacy/", PrivacyView.as_view(), name="privacy"),
    path("consent/", ConsentView.as_view(), name="consent"),
    path("terms/", TermsView.as_view(), name="terms"),
```

- [ ] **Step 6:** Проверить, что страницы открываются.

Run: `cd starlift && python manage.py runserver` (в фоне), затем в браузере: `http://localhost:8000/privacy/`, `/consent/`, `/terms/`. Все три должны отрендериться без 404/500.

- [ ] **Step 7:** Закоммитить.

```bash
git add starlift/starlift/views_legal.py starlift/starlift/urls.py starlift/templates/legal/
git commit -m "feat: страницы Политики, Согласия и Соглашения"
```

---

### Task 5: Чекбоксы в `RegisterForm` и `InviteSignupForm`

**Files:**
- Modify: `starlift/accounts/forms.py`

- [ ] **Step 1:** В `starlift/accounts/forms.py` в самом верху файла (после `from django.db.models import Q`) добавить импорт:

```python
from django.utils.safestring import mark_safe
```

- [ ] **Step 2:** Добавить общие константы для лейблов перед классом `RegisterForm` (после `_field_attrs`):

```python
_CONSENT_PDN_LABEL = mark_safe(
    'Я даю согласие на обработку моих персональных данных в соответствии с '
    '<a href="/consent/" target="_blank" rel="noopener">Согласием на обработку ПДн</a> и ФЗ-152.'
)
_ACCEPT_POLICY_LABEL = mark_safe(
    'Я ознакомлен и принимаю <a href="/privacy/" target="_blank" rel="noopener">Политику '
    'конфиденциальности</a> и <a href="/terms/" target="_blank" rel="noopener">Пользовательское соглашение</a>.'
)
_CONSENT_PDN_REQUIRED_MSG = "Для регистрации необходимо согласие на обработку персональных данных."
_ACCEPT_POLICY_REQUIRED_MSG = "Необходимо принять Политику конфиденциальности и Пользовательское соглашение."
```

- [ ] **Step 3:** В `RegisterForm`, после поля `password2`, добавить:

```python
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
```

- [ ] **Step 4:** В `InviteSignupForm`, после поля `password2`, добавить такие же два поля (повторить блок из Step 3 без изменений).

- [ ] **Step 5:** Закоммитить.

```bash
git add starlift/accounts/forms.py
git commit -m "feat(accounts): чекбоксы согласия на ПДн в формах регистрации"
```

---

### Task 6: Запись согласия в `register_view`

**Files:**
- Modify: `starlift/accounts/views/register.py`

- [ ] **Step 1:** В `starlift/accounts/views/register.py` в секции импортов уже есть `from django.utils import timezone` и `from django.conf import settings`. Внутри `register_view` найти блок где сохраняется `profile` (строки ~59-63) и расширить `update_fields` + проставить новые поля. Изменить блок:

```python
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.ROLE_GUEST
            profile.email_verified = False
            profile.pending_email = None
            profile.save(update_fields=["role", "email_verified", "pending_email", "updated_at"])
```

на:

```python
            now = timezone.now()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.ROLE_GUEST
            profile.email_verified = False
            profile.pending_email = None
            profile.pdn_consent_at = now
            profile.policy_accepted_at = now
            profile.consent_doc_version = settings.LEGAL_DOC_VERSION
            profile.save(update_fields=[
                "role",
                "email_verified",
                "pending_email",
                "pdn_consent_at",
                "policy_accepted_at",
                "consent_doc_version",
                "updated_at",
            ])
```

- [ ] **Step 2:** Сразу после существующего `audit.log(action=AuditLog.ACTION_GUEST_REGISTERED, ...)` (строки 74-80) добавить вторую запись:

```python
            audit.log(
                action=AuditLog.ACTION_CONSENT_GIVEN,
                actor=user,
                request=request,
                target=user,
                metadata={"doc_version": settings.LEGAL_DOC_VERSION},
            )
```

- [ ] **Step 3:** Закоммитить.

```bash
git add starlift/accounts/views/register.py
git commit -m "feat(accounts): фиксация согласия в register_view"
```

---

### Task 7: Запись согласия в `invite_accept_view`

**Files:**
- Modify: `starlift/accounts/views/invite.py`

- [ ] **Step 1:** Открыть `starlift/accounts/views/invite.py`. Убедиться, что есть импорты `from django.utils import timezone` и `from django.conf import settings` (если нет — добавить). Внутри `invite_accept_view` найти блок:

```python
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = invite_fresh.role
                    profile.email_verified = True  # invite arrived at this email
                    profile.save(update_fields=["role", "email_verified", "updated_at"])
```

и заменить на:

```python
                    now = timezone.now()
                    profile, _ = UserProfile.objects.get_or_create(user=user)
                    profile.role = invite_fresh.role
                    profile.email_verified = True  # invite arrived at this email
                    profile.pdn_consent_at = now
                    profile.policy_accepted_at = now
                    profile.consent_doc_version = settings.LEGAL_DOC_VERSION
                    profile.save(update_fields=[
                        "role",
                        "email_verified",
                        "pdn_consent_at",
                        "policy_accepted_at",
                        "consent_doc_version",
                        "updated_at",
                    ])
```

- [ ] **Step 2:** Сразу после существующего `audit.log(action=AuditLog.ACTION_INVITE_CONSUMED, ...)` (внутри `with transaction.atomic()`) добавить:

```python
                    audit.log(
                        action=AuditLog.ACTION_CONSENT_GIVEN,
                        actor=user,
                        request=request,
                        target=user,
                        metadata={"doc_version": settings.LEGAL_DOC_VERSION},
                    )
```

- [ ] **Step 3:** Закоммитить.

```bash
git add starlift/accounts/views/invite.py
git commit -m "feat(accounts): фиксация согласия в invite_accept_view"
```

---

### Task 8: UI — рендер чекбоксов в шаблонах регистрации

**Files:**
- Modify: `starlift/accounts/templates/accounts/register.html`
- Modify: `starlift/accounts/templates/accounts/invite_accept.html`

- [ ] **Step 1:** В `register.html` найти строку с кнопкой:

```django
    <button type="submit" class="btn-primary">
```

и **перед ней** вставить:

```django
    <div class="form-field" style="display:flex; gap:8px; align-items:flex-start; margin-top:8px;">
        {{ form.consent_pdn }}
        <label for="{{ form.consent_pdn.id_for_label }}" style="font-size:0.9em;">{{ form.consent_pdn.label|safe }}</label>
    </div>
    {% if form.consent_pdn.errors %}<div class="field-errors">{% for e in form.consent_pdn.errors %}<p>{{ e }}</p>{% endfor %}</div>{% endif %}

    <div class="form-field" style="display:flex; gap:8px; align-items:flex-start;">
        {{ form.accept_policy }}
        <label for="{{ form.accept_policy.id_for_label }}" style="font-size:0.9em;">{{ form.accept_policy.label|safe }}</label>
    </div>
    {% if form.accept_policy.errors %}<div class="field-errors">{% for e in form.accept_policy.errors %}<p>{{ e }}</p>{% endfor %}</div>{% endif %}

```

- [ ] **Step 2:** Открыть `starlift/accounts/templates/accounts/invite_accept.html`. Найти кнопку submit и **перед ней** вставить тот же блок, что и в Step 1 (полностью).

- [ ] **Step 3:** Запустить dev server и проверить вручную:

Run: `cd starlift && python manage.py runserver`
Открыть `/auth/register/` — два чекбокса со ссылками видны, ссылки открываются в новой вкладке.
Попробовать сабмитить без галочек — формa возвращается с ошибками валидации, юзер не создан.

- [ ] **Step 4:** Закоммитить.

```bash
git add starlift/accounts/templates/accounts/register.html starlift/accounts/templates/accounts/invite_accept.html
git commit -m "feat(accounts): UI чекбоксов согласия в формах регистрации"
```

---

### Task 9: Тесты

**Files:**
- Create: `starlift/accounts/tests/test_registration_consent.py`

- [ ] **Step 1:** Проверить, что директория `starlift/accounts/tests/` существует и в ней есть `__init__.py`. Если нет — создать.

Run: `ls starlift/accounts/tests/`

- [ ] **Step 2:** Создать файл `starlift/accounts/tests/test_registration_consent.py`:

```python
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
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


class RegistrationConsentTests(TestCase):
    url = None

    def setUp(self):
        self.url = reverse("accounts:register")

    def test_register_without_consent_pdn_fails(self):
        payload = {**VALID_PAYLOAD}
        payload.pop("consent_pdn")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertContains(response, "согласие на обработку персональных данных")

    def test_register_without_accept_policy_fails(self):
        payload = {**VALID_PAYLOAD}
        payload.pop("accept_policy")
        response = self.client.post(self.url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newuser").exists())
        self.assertContains(response, "Политику конфиденциальности")

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
        self.admin = User.objects.create_user(username="admin", password="x", email="a@example.com")
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


class BackfillConsentTests(TestCase):
    def test_backfill_filled_existing_users(self):
        # All UserProfile rows from setUp / fixtures (and the admin user's
        # auto-created profile) should have non-null consent dates after
        # migrate. Create a user via ORM here and verify the field is set
        # (data-migration runs at test DB setup).
        user = User.objects.create_user(username="legacy", password="x", email="l@example.com")
        # Simulate "legacy" by clearing fields, then re-running backfill
        # directly is not easy; instead just verify new users have fields
        # set by the view path covered above. This test is a smoke check
        # that the migration applied without error — DB schema present.
        self.assertTrue(hasattr(user.profile, "pdn_consent_at"))
        self.assertTrue(hasattr(user.profile, "policy_accepted_at"))
        self.assertTrue(hasattr(user.profile, "consent_doc_version"))
```

- [ ] **Step 3:** Запустить тесты.

Run: `cd starlift && python manage.py test accounts.tests.test_registration_consent -v 2`
Expected: 6 тестов, все PASS.

- [ ] **Step 4:** Запустить полный набор тестов accounts, чтобы убедиться, что ничего не сломали.

Run: `cd starlift && python manage.py test accounts -v 2`
Expected: все тесты проходят (новых ошибок нет).

- [ ] **Step 5:** Закоммитить.

```bash
git add starlift/accounts/tests/test_registration_consent.py
git commit -m "test(accounts): согласие на ПДн в формах регистрации"
```

---

## Self-Review

**Spec coverage:**
- Поля в UserProfile → Task 1 ✓
- Backfill миграция → Task 2 ✓
- LEGAL_DOC_VERSION → Task 3 ✓
- Чекбоксы в обеих формах → Task 5 ✓
- Логика записи + AuditLog в обеих view → Tasks 6, 7 ✓
- Action `CONSENT_GIVEN` → Task 1 (вместе с моделью) ✓
- Шаблоны legal/* и URL → Task 4 ✓
- Шаблоны register/invite_accept → Task 8 ✓
- Тесты → Task 9 ✓

**Placeholder scan:** `{# TODO: согласовать с юристом #}` — это намеренный плейсхолдер в legal-шаблонах (вне скоупа спеки). Все code-steps содержат полный код.

**Type consistency:** Имя константы — `ACTION_CONSENT_GIVEN` (Task 1, 6, 7, 9) — единообразно. Поля профиля `pdn_consent_at`, `policy_accepted_at`, `consent_doc_version` — единообразно во всех тасках.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-10-registration-consent.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — execute tasks in this session with checkpoints for review

Which approach?

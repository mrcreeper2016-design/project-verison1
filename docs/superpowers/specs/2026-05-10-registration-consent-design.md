# Согласие на обработку ПДн при регистрации

**Дата:** 2026-05-10
**Статус:** утверждено к реализации

## Цель

Привести регистрацию в соответствие с 152-ФЗ: пользователь не может создать
аккаунт, не подтвердив явно (1) согласие на обработку персональных данных
и (2) принятие Политики конфиденциальности и Пользовательского соглашения.
Факт согласия должен быть зафиксирован в БД для возможности доказать его
при споре или проверке.

## Затрагиваемые потоки

1. Открытая регистрация — `RegisterForm`, view `accounts.views.auth.register`.
2. Регистрация по инвайту — `InviteSignupForm`, view `accounts.views.auth.invite_accept`
   (имя view проверить по `accounts/urls.py`).

Оба потока должны требовать обе галочки.

## Модель данных

### `accounts.models.UserProfile`

Добавить три поля:

| Поле | Тип | Описание |
|------|-----|----------|
| `pdn_consent_at` | `DateTimeField(null=True, blank=True)` | Момент согласия на обработку ПДн (152-ФЗ). |
| `policy_accepted_at` | `DateTimeField(null=True, blank=True)` | Момент принятия Политики конфиденциальности и Пользовательского соглашения. |
| `consent_doc_version` | `CharField(max_length=32, blank=True, default="")` | Версия документов на момент согласия (по умолчанию текущая дата выпуска документов). |

### Миграции

- Миграция №1 — `AddField` для трёх полей.
- Миграция №2 — data-миграция backfill для существующих пользователей:
  - `pdn_consent_at = user.date_joined`
  - `policy_accepted_at = user.date_joined`
  - `consent_doc_version = "legacy"`

## Версионирование документов

Версия хранится в settings: `LEGAL_DOC_VERSION = "2026-05-10"` (строка).
При следующем обновлении текстов — менять константу. Старые согласия не
протухают; если в будущем потребуется повторное согласие — сравнение версии
позволит отфильтровать пользователей с устаревшей.

## Формы

### `RegisterForm` и `InviteSignupForm`

Добавить два поля:

```python
consent_pdn = forms.BooleanField(
    required=True,
    label=mark_safe(
        'Я даю согласие на обработку моих персональных данных в соответствии '
        'с <a href="/consent/" target="_blank" rel="noopener">'
        'Согласием на обработку ПДн</a> и ФЗ-152.'
    ),
    error_messages={"required": "Для регистрации необходимо согласие на обработку персональных данных."},
)
accept_policy = forms.BooleanField(
    required=True,
    label=mark_safe(
        'Я ознакомлен и принимаю <a href="/privacy/" target="_blank" rel="noopener">'
        'Политику конфиденциальности</a> и <a href="/terms/" target="_blank" rel="noopener">'
        'Пользовательское соглашение</a>.'
    ),
    error_messages={"required": "Необходимо принять Политику конфиденциальности и Пользовательское соглашение."},
)
```

Поля рендерятся под `password2`. Стиль чекбокса — без класса `input-compact`
(это для inputs); используем дефолтный `CheckboxInput` с обёрткой в шаблоне.

## Вьюхи

В `register` и `invite_accept` после успешного `user.save()`:

```python
now = timezone.now()
profile = user.profile  # или UserProfile.objects.get_or_create(user=user)[0]
profile.pdn_consent_at = now
profile.policy_accepted_at = now
profile.consent_doc_version = settings.LEGAL_DOC_VERSION
profile.save(update_fields=["pdn_consent_at", "policy_accepted_at", "consent_doc_version"])

AuditLog.objects.create(
    user=user,
    action=AuditLog.Action.CONSENT_GIVEN,
    ip=get_client_ip(request),
    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    meta={"doc_version": settings.LEGAL_DOC_VERSION},
)
```

Точные имена полей `AuditLog` (например `ip` vs `ip_address`, есть ли `meta`)
— уточнить при имплементации, опираясь на существующие записи в этом
файле. Если поля `meta` нет — версию положить в существующее текстовое поле
(например `details`).

Добавить новую константу действия в `AuditLog.Action`: `CONSENT_GIVEN = "consent_given"`.

## Юридические страницы

Новые URL-ы (предположительно в `starlift/starlift/urls.py` или отдельном
`legal/urls.py` — выбрать по структуре проекта при имплементации):

- `/privacy/` → `templates/legal/privacy.html`
- `/consent/` → `templates/legal/consent.html`
- `/terms/` → `templates/legal/terms.html`

Все три — простые `TemplateView`, доступны анонимам, extends `base.html`.

Тексты в шаблонах — заглушки-болванки с пометкой
`{# TODO: заменить на согласованный с юристом текст #}`. Реальный
юридический текст должен предоставить пользователь / юрист — это вне
скоупа этой задачи. Структура заглушки:

- Заголовок и дата вступления в силу (`{{ LEGAL_DOC_VERSION }}`)
- Реквизиты оператора (плейсхолдеры)
- Перечень собираемых данных
- Цели обработки
- Сроки и условия
- Контакты для отзыва согласия

## UI

Чекбоксы рендерятся вертикально под полями пароля, метка справа от
чекбокса, ссылки внутри метки открываются в новой вкладке. На ошибке
валидации — стандартный механизм Django (`form.consent_pdn.errors`).
Шаблоны: `accounts/templates/accounts/register.html` и шаблон
invite-signup (имя уточнить через grep).

## Тесты

В `accounts/tests/test_registration.py` (или существующем файле тестов
регистрации):

1. POST на регистрацию без `consent_pdn` → форма невалидна, юзер не создан.
2. POST без `accept_policy` → то же.
3. POST со всеми полями и обеими галочками → 302, юзер создан,
   `UserProfile.pdn_consent_at` и `policy_accepted_at` заполнены,
   `consent_doc_version == settings.LEGAL_DOC_VERSION`,
   в `AuditLog` есть запись с `action=CONSENT_GIVEN`.
4. То же для invite-flow.
5. Backfill: data-миграция при применении проставляет поля существующим
   пользователям (тест на миграцию или smoke-проверка через shell).

## Чек-лист имплементации (для плана)

- [ ] Миграции UserProfile (schema + data backfill)
- [ ] Константа `LEGAL_DOC_VERSION` в settings
- [ ] Поля в `RegisterForm` и `InviteSignupForm`
- [ ] Логика записи в profile + AuditLog в обеих view
- [ ] Action `CONSENT_GIVEN` в AuditLog
- [ ] Шаблоны legal/privacy.html, legal/consent.html, legal/terms.html
- [ ] URL-ы для трёх страниц
- [ ] Обновление шаблонов register.html и invite-signup.html
- [ ] Тесты (4 кейса формы + проверка миграции)

## Вне скоупа

- Реальные юридические тексты документов
- Повторное согласие при смене `LEGAL_DOC_VERSION` (модель готова к этому, но логика не реализуется сейчас)
- Cookie-баннер (отдельная история, не относится к регистрации)
- Экспорт/удаление ПДн по запросу субъекта

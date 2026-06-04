# Аутентификация, роли и доступ

Приложение `accounts` расширяет стандартный `django.contrib.auth`: профиль с ролью, инвайты, верификация email, защита от брутфорса, аудит, консоль и заявки. Связанные модели — в [data-model.md](data-model.md), маршруты — в [api.md](api.md).

---

## 1. Роли

Роль хранится в `UserProfile.role` (`accounts/models.py`):

| Роль | Константа | Доступ |
|------|-----------|--------|
| **Администратор** | `admin` | Полный CRUD спикеров, консоль, инвайты, аудит, смена ролей |
| **DevRel** | `devrel` | Управление контентом наравне с админом по большинству задач: верификация self-submitted событий (по своей `company`), приглашения, заявки, флаг «Рекомендую» |
| **Спикер** | `speaker` | Витрина (дашборд, спикеры, события, аналитика, QR) + личный кабинет `/me/` |
| **Гость** | `guest` | Только лендинг/заявочный контур; витрина закрыта |

Группировки в коде (`UserProfile`):
- `STAFF_ROLES = (admin, devrel)` — «staff», управление контентом; свойство `is_staff_member`.
- `is_member` — все, кроме гостя (admin/devrel/speaker).
- Django-`superuser` трактуется как администратор там, где это учтено (`views._is_platform_admin` → admin/devrel/superuser).

---

## 2. Декораторы доступа (`accounts/decorators.py`)

| Декоратор | Поведение |
|-----------|-----------|
| `@member_required` | Пропускает admin/devrel/speaker; гостя редиректит в `/explore/` |
| `@role_required('admin'[, …])` | Строгий гейт по конкретной роли (роли) |
| `@anonymous_required` | Уводит уже авторизованного со страниц логина/регистрации |
| `@speaker_required` (в `starlift/views_me.py`) | Роль speaker **и** привязанная карточка `Speaker`; иначе редирект |

---

## 3. Вход

- Бэкенд `accounts.auth_backends.UsernameOrEmailBackend` позволяет входить по **username или email**.
- Страница `/auth/login/`. После входа — редирект на `/` (`LOGIN_REDIRECT_URL`).
- `AUTHENTICATION_BACKENDS` содержит кастомный бэкенд + стандартный `ModelBackend`.

### Блокировка при брутфорсе

Каждая попытка пишется в `LoginAttempt`. После `ACCOUNTS_LOCKOUT_THRESHOLD` (по умолчанию **6**) неудач за `ACCOUNTS_LOCKOUT_WINDOW_SECONDS` (**60 c**) вход блокируется на это окно. Значения настраиваются через окружение. Срабатывание/снятие блокировки фиксируется в `AuditLog`.

---

## 4. Регистрация по приглашению (инвайт)

Саморегистрация на роль с доступом к витрине запрещена. Поток:

1. **admin** (или DevRel, где разрешено) создаёт инвайт в `/console/invites/`: указывает email, целевую `role` и опционально привязку к `Speaker`.
2. Генерируется одноразовый токен; по email уходит ссылка `/auth/invite/<token>/`. В БД хранится **только SHA-256 токена** (`Invite.token_hash`), не сам токен.
3. Пользователь переходит по ссылке, задаёт пароль — создаётся `User` + `UserProfile` с нужной ролью (и привязкой к спикеру, если была).
4. Инвайт «сгорает» (`used_at`/`consumed_by`). Срок жизни — `ACCOUNTS_INVITE_TTL_DAYS` (**7** дней). Инвайт можно отозвать (`revoked_at`).

Свойства `Invite`: `is_active = not (is_used or is_revoked or is_expired)`.

---

## 5. Заявка гостя на роль спикера

Альтернатива инвайту: гость после email-верификации заполняет форму `/application/` → создаётся `SpeakerApplication` (`status=pending`), маршрутизируется DevRel по полю `company`.

- **Approve** (`/console/speaker-applications/<id>/approve/`) → роль становится `speaker`, создаётся/привязывается `Speaker` (`resulting_speaker`).
- **Reject** → пользователь остаётся гостем, может переподать.

`GuestApplicationRedirectMiddleware` направляет гостя в нужный контур (заявка/ожидание).

---

## 6. Пароли, email, восстановление

- **Политика паролей** (`AUTH_PASSWORD_VALIDATORS`): минимум 8 символов; не похож на атрибуты пользователя; не из общих словарей; не только цифры; **не только спецсимволы** (`accounts.password_validators.NotOnlySpecialCharsValidator`).
- **Сброс пароля** — `/auth/password-reset/`; ссылка действует `PASSWORD_RESET_TIMEOUT` = **1 час**; анти-флуд писем — `ACCOUNTS_RESET_EMAIL_MIN_INTERVAL_SECONDS` (**300 c**).
- **Смена пароля** — `/auth/password-change/`.
- **Смена email** — из профиля; до подтверждения новый адрес лежит в `UserProfile.pending_email`, подтверждается по ссылке (`EmailVerification`, TTL `ACCOUNTS_EMAIL_CHANGE_TTL_HOURS` = **24 ч**).

---

## 7. Привязка `User ↔ Speaker`

Связка устанавливается **вручную** из консоли (`/console/users/<id>/`). После привязки `Speaker.user` карточка получает `status=authorized` (см. `Speaker.save()`), а пользователь — доступ к личному кабинету `/me/`. Также привязку можно задать через инвайт (поле `Invite.speaker`).

---

## 8. Аудит

Все значимые события пишутся в `AuditLog` и просматриваются в `/console/audit/`: логины/логаут, срабатывание/снятие блокировки, смена и сброс пароля, запрос/подтверждение смены email, обновление профиля, инвайты (создан/отозван/использован), смена роли, активация/деактивация пользователя, привязка спикера и т.д.

---

## 9. Очистка устаревших записей

```bash
cd starlift
python manage.py cleanup_stale_auth --dry-run          # показать, что будет удалено
python manage.py cleanup_stale_auth                     # применить
python manage.py cleanup_stale_auth --login-attempt-days 30
```

Чистит просроченные/использованные токены и старые `LoginAttempt`. Рекомендуется запускать по расписанию раз в сутки.

---

## 10. Параметры окружения (auth)

| Переменная | Default |
|------------|---------|
| `ACCOUNTS_LOCKOUT_THRESHOLD` | `6` |
| `ACCOUNTS_LOCKOUT_WINDOW_SECONDS` | `60` |
| `ACCOUNTS_INVITE_TTL_DAYS` | `7` |
| `ACCOUNTS_EMAIL_CHANGE_TTL_HOURS` | `24` |
| `ACCOUNTS_RESET_EMAIL_MIN_INTERVAL_SECONDS` | `300` |

Прочие настройки безопасности (secure-cookie, CSRF, HTTPS) — в [setup.md](setup.md).

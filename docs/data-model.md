# Модель данных

Описание сущностей ORM (PostgreSQL). Доменные модели — в `starlift/models.py`, модели аутентификации — в `accounts/models.py`, AI-чат — в `assistant/models.py`, поддержка — в `support/models.py`.

Связи доменного ядра:

```
User ──1:1── UserProfile          (роль, компания, аватар, верификация)
User ──1:1── Speaker (опц.)        (привязка карточки к аккаунту)

Speaker ──M:N── Event              (Event.speakers / speaker.events)
Speaker ──1:N── Feedback ──N:1── Event          (оценка зрителя)
Speaker ──1:N── SpeakerEventRating ──N:1── Event (самооценка спикера)
Speaker ──1:N── EventRequest                    (заявки create/join)
Speaker ──1:N── EventInvitation ──N:1── Event   (приглашения DevRel)
Event   ──1:N── EventPhoto                      (фотоотчёт)
User    ──1:N── SpeakerLike ──N:1── Speaker     (избранное)
User    ──1:1── SpeakerApplication              (заявка гостя на роль спикера)
```

---

## 1. Домен (`starlift/models.py`)

### Speaker — карточка спикера

| Поле | Тип | Примечание |
|------|-----|------------|
| `name` | CharField(200) | Имя и фамилия |
| `sub` | CharField(200) | Подзаголовок (должность/компания) |
| `stack` | TextField | Специализация/описание |
| `city` | CharField(100) | Город |
| `status` | choices | `unauthorized` / `authorized` — **авто** в `save()` по наличию `user` |
| `nps` | FloatField | **Кэш среднего балла** (0–10), пересчитывается при сохранении отзывов |
| `img` | CharField(100) | Legacy-поле фото (URL/число/`uploaded`); пусто = нет фото |
| `avatar` | ImageField | Загруженный аватар карточки |
| `recommended` | Bool | Флаг «Рекомендую к выдвижению» (ставит DevRel) |
| `bio` | TextField | Редактируется самим спикером в кабинете |
| `user` | O2O → User | Опциональная привязка к аккаунту (вручную из консоли) |
| `created_at` | DateTime | Для KPI новых спикеров и ленты активности |

**Методы/свойства:** `calculate_nps(event_id=None)` — средний балл по `feedbacks` + `event_ratings`; `card_avatar_url` / `avatar_url` — URL с фоллбэками (аватар аккаунта → аватар карточки → пусто). `save()` выставляет `status` по `user_id`.

> ⚠️ Если фото не загружено, `img` остаётся **пустым** — случайные аватары не подставляются.

### Event — мероприятие

| Поле | Тип | Примечание |
|------|-----|------------|
| `title` | CharField(200) | Название |
| `status` | choices | `past` / `future` |
| `date` | CharField(100) | Человекочитаемая дата (свободный текст) |
| `event_date` | DateField | Машиночитаемая дата (для расчётов периода) |
| `application_deadline` | DateField | Дедлайн подачи заявок; если не задан, но есть `event_date` — авто за 14 дней до события |
| `location`, `link`, `description`, `schedule` | — | Место, ссылка, описание, программа |
| `topic` | CharField(100) | Тема/стек события |
| `is_external` | Bool | Внешняя площадка |
| `source` | choices | `internal` / `self` / `external` / `parser` |
| `speakers` | M2M → Speaker | `related_name="events"` |
| `verification_status` | choices | `pending` / `verified` / `rejected` (для self-submit; по умолчанию `verified`) |
| `submitted_by`, `verified_by`, `verified_at`, `rejection_reason` | — | Аудит self-submission |
| `format` | choices | `online` / `offline` / `hybrid` |
| `tags`, `presentation`, `video_url` | — | Метаданные/материалы |
| `created_at` | DateTime | Для ленты активности |

**Методы:** `save()` авто-проставляет `application_deadline`; `can_self_submit()` — `True`, если дедлайн задан и не прошёл.

### EventPhoto
Фотоотчёт события (`event` FK, `image`, `uploaded_at`), загружается спикером при self-submit.

### Feedback — оценка зрителя

PK — UUID. Поля: `speaker`, `event`, `score` (0–10, CHECK-constraint), `comment`, `created_at`, `ip_address`, `session_key`. В `save()` пересчитывает и кэширует `Speaker.nps`. Защита от накруток — по cookie / `session_key` / `ip_address` + rate-limit (см. `views.submit_feedback_view`).

### SpeakerEventRating — самооценка спикера
`event`, `speaker`, `score` (0–10), `comment`. `unique_together(event, speaker)` — повторный сабмит обновляет запись. В `save()`/`delete()` пересчитывает `Speaker.nps` (учитывается наравне с отзывами зрителей).

### EventRequest — заявка спикера
`kind` = `create` (создать новое событие) | `join` (присоединиться к существующему). `status` = `pending`/`approved`/`rejected`. Поля доклада (`topic`, `comment`) и предлагаемого события (`proposed_*`). Рассматривается в консоли DevRel.

### EventInvitation — приглашение DevRel
`event`, `speaker`, `invited_by`, `status` = `pending`/`accepted`/`declined`/`cancelled`, `message`, `decline_reason`. Уникальность: один `pending`-инвайт на пару (event, speaker). Спикер отвечает из кабинета `/me/invitations/`.

### SpeakerApplication — заявка гостя на роль спикера
O2O `applicant` → User. `status` = `pending`/`approved`/`rejected`, `company`, `city`, `stack`, `description`, `resulting_speaker`. Создаётся после email-верификации; маршрутизируется DevRel по `company`. **Approve** → роль `speaker` + создание/привязка `Speaker`. **Reject** → остаётся гостем, можно переподать.

### SpeakerLike — избранное
`user`, `speaker`, `unique_together(user, speaker)`. Переключается из модалки спикера.

---

## 2. Аутентификация (`accounts/models.py`)

### UserProfile
O2O с `User` (PK). Поля: `role` (`admin`/`devrel`/`speaker`/`guest`, по умолчанию `speaker`), `company`, `email_verified`, `pending_email`, `bio`, `avatar`, согласия на ПДн (`pdn_consent_at`, `policy_accepted_at`, `consent_doc_version`), таймстемпы. Свойства: `is_admin`, `is_devrel`, `is_staff_member` (admin+devrel), `is_speaker`, `is_guest`, `is_member` (все, кроме гостя), `avatar_url`. `STAFF_ROLES = (admin, devrel)`.

### Invite
Инвайт на регистрацию: `email`, `role`, опциональная привязка `speaker`, `created_by`, **`token_hash`** (хранится только SHA-256, не сам токен), `expires_at`, `used_at`, `consumed_by`, `revoked_at`. Свойства `is_used`/`is_revoked`/`is_expired`/`is_active`.

### EmailVerification
Подтверждение смены/верификации email: `user`, `new_email`, `token_hash`, `expires_at`, `used_at`.

### LoginAttempt
Журнал попыток входа (`username_or_email`, `ip`, `success`, `created_at`) — основа блокировки при брутфорсе.

### AuditLog
Журнал значимых действий: логины/логаут, блокировки, смена/сброс пароля, смена email, обновление профиля, инвайты (создан/отозван/использован), смена роли, активация/деактивация пользователя, привязка спикера и т.д. Просмотр — `/console/audit/`.

---

## 3. AI-ассистент (`assistant/models.py`)

- **Conversation** — беседа пользователя с ассистентом: `user`, `title`, таймстемпы, `archived_at`.
- **Message** — сообщение: `conversation`, `role` (`user`/`assistant`/`tool`/`system`), `content`, поля tool-call (`tool_name`, `tool_args`, `tool_result`), учёт токенов (`token_in`, `token_out`), `created_at`.

См. [assistant.md](assistant.md).

---

## 4. Поддержка (`support/models.py`)

- **SupportTicket** — обращение (пользователь или гость по токену).
- **SupportMessage** — сообщение в тикете.
- **SupportRead** — отметки прочтения (для счётчиков непрочитанного).

См. [support.md](support.md).

---

## 5. Миграции

Миграции лежат в `*/migrations/` каждого приложения (`starlift` — 21, `accounts` — 9, `assistant` — 1). Применение:

```bash
cd starlift
python manage.py makemigrations
python manage.py migrate
```

Заметные миграции `accounts`: `0001_initial` (UserProfile, Invite, EmailVerification, LoginAttempt, AuditLog), `0002_auth_user_email_lower_index` (Postgres-индекс `LOWER(email)`), `0003_backfill_profiles` (бэкфилл профилей для существующих `User`). В `starlift` — последовательное развитие `Speaker`/`Event` (привязка `user`, `bio`, таймстемпы для ленты, дедлайны, self-submission, форматы/фото).

> При откате миграций, удаляющих `Speaker.user`/`Speaker.bio`, можно потерять ручные привязки спикеров — перед откатом делайте дамп БД.

# StarLift — архитектура

> Актуальное описание кодовой базы (как реализовано).
> **Стек:** Django 6 (монолит), PostgreSQL, серверные шаблоны + клиентский JS, GigaChat.
> Обновлено: 2026-06-03

Документ описывает **то, что есть в репозитории**, а не ранние черновики целевой архитектуры (FastAPI/React/Telegram-бот в коде отсутствуют).

---

## 1. Общий вид

```
┌──────────────┐   HTTP (HTML + JSON + SSE)   ┌──────────────────────────────────────────┐
│   Браузер    │ ───────────────────────────► │  Django (проект ``starlift``)             │
│  + лёгкий JS │                              │  • starlift   — домен (спикеры, события)  │
│  (SPA-нав.)  │ ◄─────────────────────────── │  • accounts   — auth, роли, консоль       │
└──────────────┘                              │  • assistant  — AI-чат (GigaChat)         │
                                              │  • support    — чат поддержки             │
                                              └───────┬───────────────┬───────────┬───────┘
                                                      │               │           │
                              ┌───────────────────────┘               │           └─────────────┐
                              ▼                                        ▼                         ▼
                     ┌───────────────┐                        ┌───────────────┐         ┌───────────────┐
                     │  PostgreSQL   │                        │ MEDIA / S3-R2 │         │  GigaChat API │
                     │  (ORM модели) │                        │  (аватары,    │         │  (внешний LLM)│
                     └───────────────┘                        │   фото, файлы)│         └───────────────┘
                              ▲                                └───────────────┘
                              │
                     ┌────────┴────────┐
                     │   parser/       │  ← `manage.py sync_highload` (отдельный контейнер/процесс)
                     │   Highload++    │
                     └─────────────────┘
```

- **Один web-процесс** Django (views + ORM + шаблоны), запускается под Gunicorn.
- **Импорт внешних докладов** — не микросервис, а пакет `parser/` + management-команда `sync_highload`, пишущая в те же таблицы.
- **AI-ассистент и поддержка** — внутренние Django-приложения, отдающие данные через SSE-стрим в виджеты на `base.html`.

---

## 2. Структура репозитория

```
project-verison1/
├── docs/                          # документация (этот каталог)
├── README.md
├── CLAUDE.md                      # заметки для AI-ассистента разработки
├── requirements.txt
├── Dockerfile, docker-compose.yml, entrypoint.sh, .dockerignore
└── starlift/                      # корень Django (рядом manage.py)
    ├── manage.py
    ├── starlift/                  # конфиг + домен
    │   ├── settings.py            # один файл настроек, читает .env
    │   ├── urls.py                # корневой роутер
    │   ├── models.py              # Speaker, Event, Feedback, EventRequest, …
    │   ├── views.py               # страницы + JSON API (домен)
    │   ├── views_me.py            # личный кабинет спикера (/me/…)
    │   ├── forms.py               # SpeakerForm, FeedbackForm, загрузка событий
    │   ├── analytics.py           # NPS, распределения, кандидаты на выдвижение
    │   ├── home_metrics.py        # KPI и блоки главной (/api/home/)
    │   ├── admin.py
    │   └── management/commands/   # sync_highload, seed_demo_feedbacks
    ├── accounts/                  # аутентификация и консоль
    │   ├── models.py              # UserProfile, Invite, EmailVerification, LoginAttempt, AuditLog
    │   ├── decorators.py          # member_required, role_required, anonymous_required
    │   ├── middleware.py          # GuestApplicationRedirectMiddleware
    │   ├── auth_backends.py       # вход по username ИЛИ email
    │   ├── password_validators.py # доп. валидатор пароля
    │   ├── context_processors.py  # header_avatar_url
    │   ├── views/                 # auth, register, invite, password, email, profile, console, speaker_application
    │   ├── services/              # speaker_avatar и пр.
    │   ├── templates/accounts/    # auth + console + profile
    │   └── management/commands/   # cleanup_stale_auth, migrate_avatars_to_object_storage
    ├── assistant/                 # AI-чат на GigaChat
    │   ├── models.py              # Conversation, Message
    │   ├── agent/                 # loop.py, gigachat_client.py, budget.py, tools/
    │   ├── services/              # rate_limit и пр.
    │   └── views/                 # chat (SSE), conversations
    ├── support/                   # чат поддержки
    │   ├── models.py              # SupportTicket, SupportMessage, SupportRead
    │   ├── urls.py, urls_guest.py
    │   └── views/                 # tickets, stream (SSE), api, guest
    ├── parser/                    # импорт внешних докладов
    │   ├── highload.py            # разбор HTML Highload++
    │   ├── highload_importer.py   # запись в ORM (Speaker/Event, M2M)
    │   └── tavily_parser.py       # вспомогательная интеграция (необязательный контур)
    ├── templates/                 # base.html, index, speakers, events, analytics, qr_*, me/…
    ├── static/                    # CSS/JS/ассеты
    └── media/                     # загружаемые файлы (если не object storage)
```

---

## 3. Приложение `starlift` (домен)

### 3.1 Модели

Полное описание полей и связей — в [data-model.md](data-model.md). Кратко:

| Модель | Назначение |
|--------|------------|
| **Speaker** | Карточка спикера. Опциональная O2O-связь с `User`; `status` авто-выставляется в `authorized`/`unauthorized` в `save()`. Поле `nps` — кэш среднего балла. |
| **Event** | Мероприятие. M2M `speakers`. Поля `source` (internal/self/external/parser), `status` (past/future), `verification_status` (для self-submit), `application_deadline`. |
| **EventPhoto** | Фотоотчёт события (загружается спикером при self-submit). |
| **Feedback** | Оценка выступления зрителем (0–10). В `save()` пересчитывает `Speaker.nps`. |
| **SpeakerEventRating** | Самооценка спикера за событие (0–10), одна на пару (speaker, event). Тоже влияет на `Speaker.nps`. |
| **EventRequest** | Заявка спикера: создать событие (`create`) или присоединиться (`join`). |
| **EventInvitation** | Приглашение DevRel спикеру на событие. |
| **SpeakerApplication** | Заявка гостя на получение роли спикера (одобряет DevRel по `company`). |
| **SpeakerLike** | Лайк/избранное спикера от пользователя. |

Доменное ядро: **Speaker ↔ Event (M2M)** + оценки (`Feedback`, `SpeakerEventRating`).

### 3.2 Расчёт NPS (важный нюанс)

В коде есть **две разные величины**, обе исторически называются «NPS»:

1. **`Speaker.nps`** — это **средний балл (0–10)** по всем отзывам зрителей и самооценкам спикера. Считается в `Speaker.calculate_nps()` как `round(sum(scores)/len(scores), 1)` и кэшируется в поле при каждом `Feedback.save()` / `SpeakerEventRating.save()`.
2. **Классический NPS** `(promoters% − detractors%)` (промоутеры: балл ≥ 9, детракторы: ≤ 6) — считается **на лету** в `analytics.compute_nps()` для распределений, а в `home_metrics.top_speakers()` промоутеры/детракторы используются как вторичный ключ сортировки лидерборда.

То есть на карточках и в KPI обычно показывается **средний балл**, а проценты промоутеров/детракторов — вспомогательная аналитика. Поле `Speaker.nps` — кэш, не источник истины (источник — отзывы).

### 3.3 Страницы и API

См. [api.md](api.md). Кратко:

- **HTML-страницы:** `/` (главная), `/explore/` (гостевой лендинг), `/speakers/`, `/events/`, `/analytics/`, формы спикера, `/qr-generator/`, публичная оценка `/rate/<event>/<speaker>/`, кабинет `/me/…`.
- **JSON API:** `/api/speakers/`, `/api/events/`, `/api/home/`, `/api/notifications/`, лайки/рекомендации, заявки и быстрые одобрения.
- **Доступ** ограничен декораторами `member_required` (admin/devrel/speaker) и `role_required('admin')`; кабинет `/me/` — `speaker_required`.

### 3.4 Аналитика и метрики

- **`analytics.py`** — разбор фильтров (период, город, тема, порог NPS), распределения оценок, **отбор кандидатов на выдвижение** (средний балл ≥ порог, частота событий за окно, флаг `recommended`).
- **`home_metrics.py`** — данные главного дашборда: KPI, ближайшие события, топ спикеров (для admin/devrel), лента активности (admin/devrel), «Ваши мероприятия» (для спикера), плюс `version`-хэш для лёгкого поллинга `/api/home/`.

### 3.5 Личный кабинет спикера (`views_me.py`)

Маршруты `/me/…` под декоратором `speaker_required` (роль `speaker` + привязанная карточка `Speaker`). Разделы: дашборд, свои мероприятия (с загрузкой прошедших и самооценкой), отзывы (+ экспорт CSV), приглашения от DevRel (принять/отклонить), заявки, избранное.

### 3.6 QR-коды

- `/qr-generator/` — выбор пары спикер↔событие (комбобоксы взаимно фильтруются по M2M).
- `/speaker/<id>/event/<id>/qr/` — страница с QR; `/…/qr/poster.png` — печатный PNG-постер (шрифт DejaVu из `starlift/assets/fonts/`, чтобы кириллица рендерилась на любом сервере).
- Админ/DevRel — любая валидная пара; спикер — только своя карточка и только события из своего M2M-набора.

---

## 4. Приложение `accounts`

Полное описание — в [auth-roles.md](auth-roles.md). Кратко:

- **Роли (`UserProfile.role`):** `admin`, `devrel`, `speaker`, `guest`. `admin`+`devrel` — «staff» (управление контентом). Связка `User ↔ Speaker` — вручную из консоли.
- **Вход** по `username` **или** `email` (`auth_backends.UsernameOrEmailBackend`).
- **Регистрация** только по инвайту; гость может подать `SpeakerApplication` на роль спикера.
- **Защита:** блокировка при брутфорсе (`LoginAttempt`), верификация email (`EmailVerification`), аудит (`AuditLog`).
- **Консоль** `/console/…` для admin/devrel: пользователи, инвайты, аудит, заявки на события, приглашения, заявки спикеров, верификация self-submitted событий.
- **Middleware** `GuestApplicationRedirectMiddleware` направляет гостя в заявочный/landing-контур.

---

## 5. Приложения `assistant` и `support`

Оба — **drawer-виджеты** (без отдельных страниц), подключаются в `templates/base.html` и общаются с бэкендом через JSON + **SSE** (Server-Sent Events).

- **`assistant`** — AI-чат на GigaChat. Agent-loop с tool-calling (read-only инструменты по данным платформы), бюджеты токенов и rate-limit. См. [assistant.md](assistant.md).
- **`support`** — чат поддержки: тикеты и сообщения, real-time через SSE; отдельный контур для гостей по токену (`/support/…`). См. [support.md](support.md).

---

## 6. Фронтенд

- **Рендер:** серверные Django-шаблоны, общая оболочка `templates/base.html` (навигация, тема, фон, FAB-виджеты ассистента и поддержки).
- **«SPA»-навигация:** перехват кликов по `.nav-item`, `fetch` целой страницы, извлечение `#page-content` и `#page-modals`, подстановка в DOM и **повторное выполнение** встроенных `<script>`. Событие `spa-page-loaded` инициализирует страницу.
- **Данные:** страницы тянут JSON с `/api/...`, рендерят таблицы/карточки/модалки на ванильном JS; главная поллит `/api/home/` каждые 15 c и перерисовывается только при смене `version`.
- **Стили:** в основном `<style>` внутри шаблонов + CSS-переменные для светлой/тёмной темы (`data-theme`). Графики аналитики — Chart.js. Бандлера/Node-сборки нет.

---

## 7. Потоки данных

1. **Ручной/админский ввод.** admin/DevRel создают и правят `Speaker`/`Event` через views и `/admin/`, связывают M2M, привязывают `Speaker.user`.
2. **Самовыдвижение.** Спикер из кабинета загружает прошедшее мероприятие (`source=self`, `verification_status=pending`) → DevRel его компании подтверждает/отклоняет. Также: заявки на создание/участие (`EventRequest`) и ответы на приглашения (`EventInvitation`).
3. **Парсинг Highload++.** `sync_highload` дёргает `parser.highload_importer`, создаёт/обновляет `Speaker`/`Event` с `source=parser`, ставит M2M, отсекает дубли. См. [parser.md](parser.md).
4. **Оценки аудитории.** Публичная форма `/rate/<event>/<speaker>/` создаёт `Feedback`; `Speaker.nps` обновляется в `Feedback.save()`.
5. **Демо-данные.** `seed_demo_feedbacks [--clear]` — массовая генерация отзывов для разработки.

---

## 8. Технологии (фактические)

| Компонент | Реализация |
|-----------|------------|
| Web-фреймворк | **Django 6.0** (`requirements.txt`) |
| ORM / миграции | Django ORM (`starlift/migrations`, `accounts/migrations`, `assistant/migrations`) |
| БД | **PostgreSQL** (16-alpine в docker-compose) |
| Шаблоны | Django Templates + ванильный JS |
| Графики | **Chart.js** (в шаблоне аналитики) |
| QR | библиотека **qrcode** + **Pillow** (PNG-постер) |
| AI | **GigaChat** через пакет `gigachat` |
| Парсинг | **requests** + **beautifulsoup4** |
| Статика | **WhiteNoise** (`CompressedManifestStaticFilesStorage`) |
| Медиа | `MEDIA_ROOT` или **django-storages** (S3/R2) при `USE_OBJECT_STORAGE=true` |
| Сервер | **Gunicorn** (3 воркера в Docker) |
| Конфиг | **python-dotenv**, `.env` в `starlift/` |

---

## 9. Безопасность и эксплуатация (кратко)

- Стандартный Django: CSRF на формах, сессии, хеширование паролей; расширенная политика паролей (`accounts/password_validators.py`).
- Блокировка при брутфорсе и аудит административных действий (`AuditLog`, просмотр в консоли).
- Доверие заголовку `X-Forwarded-Proto` (за nginx/прокси), безопасные cookie при `DEBUG=False`.
- Перед продакшеном: свой `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`, HTTPS, резервное копирование БД. См. [setup.md](setup.md).

---

## 10. Резюме

**StarLift** — монолитный Django-проект из четырёх приложений (`starlift`, `accounts`, `assistant`, `support`) с серверным HTML-интерфейсом и лёгкой SPA-навигацией. Доменная модель строится вокруг **Speaker ↔ Event (M2M)** и оценок; отдельного сервиса скоринга нет — аналитика и отбор кандидатов реализованы в Python поверх ORM. Внешний контент Highload++ подтягивается парсером и management-командой. AI-ассистент и поддержка встроены как SSE-виджеты, изолируя внешний LLM (GigaChat) в одном клиентском модуле.

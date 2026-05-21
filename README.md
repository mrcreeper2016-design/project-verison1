# StarLift

**StarLift** — это платформа (MVP) для учёта, оценки и управления корпоративными спикерами. Проект автоматизирует сбор данных об участии сотрудников в конференциях, анализирует их активность (формируя скоринг) и предоставляет удобный дашборд для HR-специалистов и DevRel-менеджеров.

## ✨ Ключевые возможности

*   **Централизованная база спикеров и мероприятий:** Единое хранилище всех выступлений и спикеров компании, их специализаций (stack), статусов и других метрик.
*   **Автоматический парсинг конференций:** Встроенные скрипты скрапинга (playwright и др.) собирают информацию о предстоящих и прошедших IT-конференциях с внешних площадок (таких как Ontico, HighLoad++ и др.).
*   **Дашборд и Аналитика:** Удобный веб-интерфейс на базе Django templates для просмотра списка спикеров, оценки NPS, фильтрации и мониторинга событий.
*   **Скоринг и шорт-листы кандидатов:** Анализ текущей активности спикеров для выбора наиболее подходящих кандидатов на федеральные и профильные конференции.

---

## 🛠 Технологический стек

*   **Backend:** Python 3.10+, Django
*   **База данных:** PostgreSQL 
*   **Скрапинг и парсинг:** playwright, модули для интеграции с внешними API (например, Tavily).
*   **Frontend-шаблонизация:** Django Templates (HTML, CSS, JS), базовая аналитика и дашборды.
*   **Архитектурный подход:** Модульный монолит с перспективой выделения сервисов.

---

## 📂 Структура проекта

Ниже представлено описание ключевых компонентов и файлов, входящих в MVP:

- 📄 **`README.md`** — Эта документация.
- 📄 **`requirements.txt`** — Список Python-зависимостей проекта.
- 📁 **`docs/`** — Архитектура проекта и спецификации (например, `architecture.md`).
- 📁 **`starlift/`** — Основная рабочая директория Django-приложения:
  - 📄 **`manage.py`** — Утилита командной строки и точка управления Django.
  - 📁 **`starlift/`** — Ядро приложения (backend):
    - `settings.py` — Глобальные настройки (подключение БД, middleware).
    - `models.py` — Описание структуры базы данных (сущности Speaker, Event).
    - `urls.py` — Маршрутизация роутов API и страниц сайта.
    - `views.py` — Основная бизнес-логика (работа с данными и рендер шаблонов).
  - 📁 **`parser/`** — Модули для автоматизированного сбора данных о конференциях:
    - `highload.py`, `highload_importer.py` — разбор страниц Highload++ и импорт в БД через `sync_highload`;
    - `parser_ontico.py`, `ontico_scraper_db.py` — скраперы для других IT-мероприятий.
    - `tavily_parser.py` — Интеграция с внешним API Tavily.
  - 📁 **`templates/`** — Графический интерфейс, HTML-шаблоны страниц:
    - Дашборд (`index.html`), аналитика (`analytics.html`), списки и профили (`speakers.html`, `profile.html`, `events.html`).
  - 📁 **`media/`** — Директория загружаемых пользовательских файлов и фотографий спикеров.
  - 📁 **`static/`** — Директория статических файлов (темы оформления CSS, скрипты).

---

## ⚙️ Как работает система

1. **Сбор данных:** Автономные скрипты в папке parser/ анализируют сайты ключевых IT-конференций (Ontico, HighLoad) и собирают данные через веб-скрапинг. Полученные данные (спикеры, доклады) подготавливаются и заносятся в основную базу.
2. **Управление и хранение (Backend):** В models.py приложения описаны базовые сущности:
   * **Speaker** — содержит специализацию (stack), город, статус, метрику NPS, фотографию и т.д.
   * **Event** — содержит описание мероприятий, даты, статусы (past / uture) и данные о расписаниях докладов.
3. **Отображение (Frontend):** Итоговые данные маршрутизируются через iews.py в шаблоны директории 	emplates/. Пользователям (как правило HR/DevRel) предоставляется консоль в виде аналитических графиков (nalytics.html), каталога корпоративных спикеров (speakers.html) и списков конференций.

---

## 🚀 Установка и запуск (локально)

### Требования
* Python 3.10+
* PostgreSQL
* Python benv

### Шаги установки:

> в разработке...

## 🔐 Аутентификация и роли

StarLift использует кастомное приложение `accounts` поверх стандартного `django.contrib.auth`.

**Роли:**
- `admin` — полный доступ к CRUD спикеров, invite-ам, console, аудиту.
- `speaker` — доступ к дашборду, списку спикеров/событий и личному кабинету.

**Основные потоки:**
- **Регистрация только по приглашению.** Админ создаёт инвайт в `/console/invites/`; токен доставляется письмом (ссылка `/auth/invite/<token>/`) и одноразовый.
- **Логин** по `username` или `email` на `/auth/login/`. Блокировка после 6 неудач подряд в течение 60 секунд (`ACCOUNTS_LOCKOUT_THRESHOLD` / `ACCOUNTS_LOCKOUT_WINDOW_SECONDS`).
- **Восстановление пароля** через `/auth/password-reset/` (email со ссылкой, действительной 1 час).
- **Смена email** в профиле требует подтверждения по ссылке; до подтверждения хранится в `UserProfile.pending_email`.
- **Связка `User ↔ Speaker`** выполняется вручную администратором из карточки пользователя (`/console/users/<id>/`).

**Политика паролей:** минимум 8 символов; не только цифры; не только спецсимволы; валидация по общим словарям + сходству с атрибутами пользователя.

**Аудит:** все значимые события (логины, сбросы, изменения ролей, инвайты, связки) пишутся в `accounts_audit_log` и просматриваются в `/console/audit/`.

**Очистка устаревших записей:**
```bash
python manage.py cleanup_stale_auth --dry-run          # показать
python manage.py cleanup_stale_auth                     # применить
python manage.py cleanup_stale_auth --login-attempt-days 30
```
Запускать раз в сутки по расписанию.

### Highload++ (`sync_highload`)

Доклады с `highload.ru` сохраняются **напрямую в PostgreSQL** (модели `Speaker`, `Event`, связь M2M). **CSV не используется.**

Разовый проход:

```bash
cd starlift
python manage.py sync_highload --once
```

Цикл с паузой между проходами (интервал по умолчанию 30 минут — задайте флагом или `HIGHLOAD_INTERVAL_MINUTES` в `.env`):

```bash
python manage.py sync_highload --interval-minutes 30
```

`--max-cycles N` ограничивает число итераций (удобно для отладки). Список URL — `HIGHLOAD_URLS` в `.env`, пример в `starlift/.env.example`.

---

## ⚙️ Переменные окружения

Положите файл `.env` в `starlift/` (рядом с `manage.py`). Пример:

```dotenv
# Database (Postgres)
DB_ENGINE=django.db.backends.postgresql
DB_NAME=starlift_db
DB_USER=starlift
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=5432

# Email (console backend for dev, SMTP for prod)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=no-reply@starlift.local
EMAIL_HOST_PASSWORD=change-me
EMAIL_USE_TLS=true
DEFAULT_FROM_EMAIL=no-reply@starlift.local
SITE_URL=https://starlift.example.com

# Auth tuning (defaults shown)
ACCOUNTS_LOCKOUT_THRESHOLD=6
ACCOUNTS_LOCKOUT_WINDOW_SECONDS=60
ACCOUNTS_INVITE_TTL_DAYS=7
ACCOUNTS_EMAIL_CHANGE_TTL_HOURS=24
ACCOUNTS_RESET_EMAIL_MIN_INTERVAL_SECONDS=300

# Highload++ parser (`python manage.py sync_highload`)
HIGHLOAD_URLS=https://highload.ru/moscow/2025/abstracts,https://highload.ru/spb/2026/abstracts
HIGHLOAD_INTERVAL_MINUTES=30
HIGHLOAD_REQUEST_TIMEOUT=20
HIGHLOAD_MAX_RETRIES=3

# Object storage (S3-compatible, recommended free option: Cloudflare R2)
USE_OBJECT_STORAGE=false
STORAGE_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
STORAGE_BUCKET_NAME=starlift-media
STORAGE_ACCESS_KEY=<r2-access-key-id>
STORAGE_SECRET_KEY=<r2-secret-access-key>
STORAGE_REGION=auto
# Public base URL for serving media files (R2 custom domain or CDN)
STORAGE_PUBLIC_BASE_URL=https://media.example.com
# Optional: auto | virtual | path
STORAGE_ADDRESSING_STYLE=auto
```

В продакшене также выставьте `DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, включите HTTPS (`SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`).

---

## 🗂 Object Storage и миграция аватаров

Для хранения аватаров в bucket включите:

```dotenv
USE_OBJECT_STORAGE=true
```

После настройки переменных storage выполните миграции и перенос legacy-файлов:

```bash
cd starlift
python manage.py migrate
python manage.py migrate_avatars_to_object_storage --dry-run
python manage.py migrate_avatars_to_object_storage
```

`migrate_avatars_to_object_storage` переносит legacy-аватары спикеров из путей вида `/media/...` в новое поле `Speaker.avatar`.

---

## 🧪 Тесты

```bash
cd starlift
python manage.py test accounts
python manage.py test starlift
```

Покрывают: валидаторы паролей, backend логина, lockout, токены, аудит, login-flow, password reset/change, invite flow (create/revoke/accept), профиль, email change, admin console (link-speaker, unlock, role change); парсинг Highload, импорт в БД без дубликатов, management-команда `sync_highload`.

### Smoke-checklist после включения object storage

1. Войти под администратором и загрузить аватар в личном кабинете (`/profile/`).
2. Убедиться, что аватар отображается в header (правый верхний блок профиля).
3. Создать/изменить спикера с новым изображением и проверить карточки в `/speakers/`, `/analytics/`, `/`.
4. Запустить `python manage.py migrate_avatars_to_object_storage --dry-run` и проверить отчёт без ошибок.
5. Запустить `python manage.py migrate_avatars_to_object_storage` и убедиться, что legacy `/media/...` аватары доступны из bucket URL.

---

## 🔄 Rollback миграций accounts + starlift

Миграции, добавленные в этой итерации:

| app        | migration                               | смысл                                            |
|------------|-----------------------------------------|--------------------------------------------------|
| accounts   | `0001_initial`                          | UserProfile, Invite, EmailVerification, LoginAttempt, AuditLog |
| accounts   | `0002_auth_user_email_lower_index`      | Postgres: уникальный индекс `LOWER(email)`       |
| accounts   | `0003_backfill_profiles`                | Бэкфилл UserProfile для существующих User        |
| starlift   | `0009_speaker_bio_speaker_user`         | Добавляет `Speaker.bio` и `Speaker.user` (O2O)   |

Откат полной итерации:

```bash
# 1) Откатить код до предыдущего коммита (accounts app отсутствует).
git revert <merge-commit>

# 2) Откатить миграции в обратном порядке:
python manage.py migrate starlift 0008_home_timestamps
python manage.py migrate accounts zero

# 3) Удалить каталог accounts/ из кода (если остался), рестартнуть процесс.
```

Важное:
- `accounts.0002_auth_user_email_lower_index` безопасно откатывается — индекс удаляется.
- `accounts.0003_backfill_profiles` при откате чистит `accounts_userprofile`; данные без миграций не теряются, роли можно восстановить повторным бэкфиллом.
- `starlift.0009` удаляет `Speaker.bio` и `Speaker.user`, что может потерять ручные привязки спикеров к пользователям — перед откатом сделайте дамп.

---

## 📖 Архитектура
Дополнительная документация и схема архитектуры находятся в docs/architecture.md.

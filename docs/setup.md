# Установка, запуск и эксплуатация

Все Django-команды выполняются из каталога `starlift/` (там лежит `manage.py`).

---

## 1. Требования

- **Python 3.12** (Docker-образ `python:3.12-slim`; локально подойдёт 3.11+)
- **PostgreSQL** 14+ (в Docker используется `postgres:16-alpine`)
- Для сборки `psycopg2` локально на Linux — системные пакеты `build-essential`, `libpq-dev`

---

## 2. Запуск через Docker (рекомендуется)

`docker-compose.yml` поднимает три сервиса: `db` (Postgres), `web` (Gunicorn) и `parser` (цикл `sync_highload`).

```bash
# 1. Окружение (web и parser читают starlift/.env.production)
cp starlift/.env.example starlift/.env.production
#   отредактируйте DB_*, SECRET_KEY, ALLOWED_HOSTS, GIGACHAT_* …

# 2. Сборка и запуск
docker compose up -d --build

# 3. Суперпользователь
docker compose exec web python manage.py createsuperuser

# Логи / остановка
docker compose logs -f web
docker compose down
```

Особенности:

- Контейнер `web` запущен с `RUN_MIGRATIONS=true` → `entrypoint.sh` дожидается БД, прогоняет `migrate` и `collectstatic`. Контейнер `parser` миграции **не** запускает.
- Порт проброшен на `127.0.0.1:8000` (за внешним nginx/прокси). Django доверяет `X-Forwarded-Proto`.
- Том `mediafiles` хранит загруженные файлы (если не включён object storage), том `pgdata` — данные Postgres.
- Переменные БД для контейнера `db` берутся из `.env.production` (`DB_NAME`, `DB_USER`, `DB_PASSWORD`) — для Postgres они мапятся в `POSTGRES_*`.

---

## 3. Локальный запуск (без Docker)

```bash
# из корня репозитория
python -m venv .venv
.venv\Scripts\activate            # Windows (PowerShell)
# source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt

cd starlift
cp .env.example .env              # пропишите DB_* (Postgres должен быть запущен)
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Откройте `http://127.0.0.1:8000`. Для входа используйте суперпользователя; роль ему можно выставить в `/admin/` или консоли (`UserProfile.role = admin`).

> Email в dev по умолчанию печатается в консоль (`console.EmailBackend`) — ссылки из писем (инвайты, сброс пароля, верификация) ищите в логах сервера.

---

## 4. Переменные окружения

Файл `.env` кладётся в `starlift/` (рядом с `manage.py`). Какой файл читать, определяется в `settings.py`:

1. `ENV_FILE=/path/to/file` — явный путь (приоритет);
2. `DJANGO_ENV=production` → `starlift/.env.production`;
3. иначе → `starlift/.env`.

Переменные ОС всегда перекрывают значения из файла. Шаблон — `starlift/.env.example`.

### 4.1 Ядро / безопасность

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `SECRET_KEY` | небезопасный dev-ключ | **Обязательно задать** в проде |
| `DEBUG` | `False` | `True` только для разработки |
| `ALLOWED_HOSTS` | localhost + ngrok | Список хостов через запятую |
| `CSRF_TRUSTED_ORIGINS` | ngrok | Доверенные origin для CSRF |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | `True` при `DEBUG=False` | Secure-cookie |

### 4.2 База данных

| Переменная | По умолчанию |
|------------|--------------|
| `DB_ENGINE` | `django.db.backends.postgresql` |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | — |
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |

### 4.3 Email

`EMAIL_BACKEND` (по умолчанию `console.EmailBackend`), `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_TIMEOUT`, `DEFAULT_FROM_EMAIL`, `SITE_URL`. Для прода переключите backend на SMTP.

### 4.4 Аутентификация

| Переменная | Default | Назначение |
|------------|---------|------------|
| `ACCOUNTS_LOCKOUT_THRESHOLD` | `6` | Неудачных логинов до блокировки |
| `ACCOUNTS_LOCKOUT_WINDOW_SECONDS` | `60` | Окно блокировки |
| `ACCOUNTS_INVITE_TTL_DAYS` | `7` | Срок жизни инвайта |
| `ACCOUNTS_EMAIL_CHANGE_TTL_HOURS` | `24` | Срок токена смены email |
| `ACCOUNTS_RESET_EMAIL_MIN_INTERVAL_SECONDS` | `300` | Анти-флуд писем сброса |

### 4.5 Парсер Highload++

`HIGHLOAD_URLS` (список URL через запятую), `HIGHLOAD_INTERVAL_MINUTES` (`30`), `HIGHLOAD_REQUEST_TIMEOUT` (`20`), `HIGHLOAD_MAX_RETRIES` (`3`). См. [parser.md](parser.md).

### 4.6 AI-ассистент (GigaChat)

`GIGACHAT_AUTH_KEY`, `GIGACHAT_SCOPE` (`GIGACHAT_API_PERS`), `GIGACHAT_MODEL` (`GigaChat-Pro`), `GIGACHAT_VERIFY_SSL` (`false`), плюс `ASSISTANT_*` (включение, лимиты, бюджеты токенов). Полный список — в [assistant.md](assistant.md). Без `GIGACHAT_AUTH_KEY` ассистент не сможет обращаться к LLM.

### 4.7 Чат поддержки

`SUPPORT_RATE_LIMIT_PER_USER` (`30`), `SUPPORT_RATE_LIMIT_PER_GUEST` (`5`), `SUPPORT_RATE_LIMIT_WINDOW_SECONDS` (`300`). См. [support.md](support.md).

### 4.8 Object storage (S3/R2)

`USE_OBJECT_STORAGE` (`false`). При `true` дополнительно: `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET_NAME`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `STORAGE_REGION`, `STORAGE_PUBLIC_BASE_URL`, `STORAGE_ADDRESSING_STYLE`. См. раздел 6.

---

## 5. Management-команды

| Команда | Назначение |
|---------|------------|
| `python manage.py sync_highload --once` | Один проход парсера Highload++ |
| `python manage.py sync_highload --interval-minutes 30 [--max-cycles N]` | Цикл с паузой |
| `python manage.py cleanup_stale_auth --dry-run` | Очистка устаревших токенов/попыток входа (preview) |
| `python manage.py cleanup_stale_auth [--login-attempt-days 30]` | То же, применить |
| `python manage.py seed_demo_feedbacks [--clear]` | Демо-отзывы для разработки |
| `python manage.py migrate_avatars_to_object_storage --dry-run` | Перенос legacy-аватаров в bucket (preview) |

`cleanup_stale_auth` имеет смысл запускать по расписанию раз в сутки.

---

## 6. Object Storage и миграция аватаров

По умолчанию аватары и файлы лежат в `MEDIA_ROOT` (`starlift/media/`). Чтобы хранить их в S3-совместимом бакете (протестировано на **Cloudflare R2**):

```dotenv
USE_OBJECT_STORAGE=true
STORAGE_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
STORAGE_BUCKET_NAME=starlift-media
STORAGE_ACCESS_KEY=<access-key-id>
STORAGE_SECRET_KEY=<secret-access-key>
STORAGE_REGION=auto
STORAGE_PUBLIC_BASE_URL=https://media.example.com   # публичный домен/CDN бакета
STORAGE_ADDRESSING_STYLE=auto                       # auto | virtual | path
```

`settings.py` валидирует обязательные переменные и настраивает `django-storages` (`S3Storage`). Затем:

```bash
cd starlift
python manage.py migrate
python manage.py migrate_avatars_to_object_storage --dry-run
python manage.py migrate_avatars_to_object_storage
```

Команда переносит legacy-аватары спикеров из путей `/media/...` в поле `Speaker.avatar`.

### Smoke-чеклист после включения object storage

1. Войти администратором, загрузить аватар в `/profile/`.
2. Проверить, что аватар виден в шапке (правый верхний угол).
3. Создать/изменить спикера с изображением, проверить карточки в `/speakers/`, `/analytics/`, `/`.
4. `migrate_avatars_to_object_storage --dry-run` — отчёт без ошибок.
5. Запустить миграцию и убедиться, что legacy `/media/...` аватары доступны по URL бакета.

---

## 7. Production-чеклист

- [ ] `SECRET_KEY` — собственный, из секретов окружения (не из репозитория).
- [ ] `DEBUG=False`.
- [ ] `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` — реальные домены.
- [ ] HTTPS на уровне прокси; `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` = `True` (по умолчанию при `DEBUG=False`).
- [ ] SMTP-backend для email и валидный `DEFAULT_FROM_EMAIL` / `SITE_URL`.
- [ ] Прогнаны `migrate` и `collectstatic` (в Docker — автоматически на старте `web`).
- [ ] Настроено резервное копирование Postgres (том `pgdata`).
- [ ] (Опц.) object storage для медиа, если несколько инстансов/эфемерная ФС.
- [ ] (Опц.) расписание `cleanup_stale_auth` и мониторинг логов парсера.

---

## 8. Тесты

```bash
cd starlift
python manage.py test            # всё
python manage.py test accounts   # auth, инвайты, lockout, профиль, консоль
python manage.py test starlift   # модели, NPS, парсер, кабинет, дедлайны, дашборд
python manage.py test assistant  # инструменты и agent-loop ассистента
```

Тестовая БД создаётся и удаляется автоматически (нужны права на `CREATE DATABASE` у `DB_USER`).

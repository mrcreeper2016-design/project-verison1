# StarLift

**StarLift** — платформа для учёта, оценки и продвижения корпоративных спикеров. Система собирает в едином окне данные о выступлениях сотрудников (внутренние отчёты, самовыдвижение и автоматический парсинг внешних площадок), считает по ним метрики качества и помогает HR-бренду и DevRel объективно выбирать кандидатов на федеральные конференции.

Технически это **монолит на Django** с серверным рендерингом шаблонов и лёгкой SPA-навигацией, PostgreSQL, парсером Highload++, AI-ассистентом на GigaChat и встроенным чатом поддержки.

---

## 📚 Документация

Подробная документация вынесена в каталог [`docs/`](docs/):

| Документ | О чём |
|----------|-------|
| [docs/architecture.md](docs/architecture.md) | Архитектура: приложения, потоки данных, фронтенд, технологии |
| [docs/setup.md](docs/setup.md) | Установка локально, запуск через Docker, production-чеклист |
| [docs/data-model.md](docs/data-model.md) | Модели БД, связи, расчёт NPS, миграции |
| [docs/api.md](docs/api.md) | HTTP-маршруты: страницы, JSON API, SSE-эндпоинты |
| [docs/auth-roles.md](docs/auth-roles.md) | Аутентификация, роли, инвайты, заявки, аудит, политика паролей |
| [docs/parser.md](docs/parser.md) | Парсер Highload++ и команда `sync_highload` |
| [docs/assistant.md](docs/assistant.md) | AI-ассистент на GigaChat (tool-calling, бюджеты, SSE) |
| [docs/support.md](docs/support.md) | Чат поддержки (пользователи и гости) |

---

## ✨ Ключевые возможности

- **Единая база спикеров и мероприятий.** Карточки спикеров (специализация, город, NPS, фото, привязка к аккаунту) и события с M2M-связью «спикер ↔ мероприятие».
- **Три контура ввода данных.** Внутренние отчёты (админ/DevRel), самовыдвижение спикера (загрузка прошедших мероприятий с верификацией DevRel) и автоматический парсинг Highload++.
- **Дашборд и аналитика.** Главный «оперативный центр» (KPI, ближайшие события, топ спикеров, лента активности), страница аналитики с графиками (Chart.js), фильтры по NPS, городу, теме, периоду.
- **Скоринг и кандидаты на выдвижение.** Автоотбор по порогам: средний балл ≥ 9.4, частота ≥ 2 событий за полгода, учёт флага «Рекомендую» от DevRel.
- **Личный кабинет спикера (`/me/`).** Свои мероприятия, отзывы (с экспортом в CSV), приглашения от DevRel, заявки, избранное.
- **Сбор отзывов через QR.** Печатный постер с QR ведёт на публичную форму оценки выступления (0–10).
- **AI-ассистент на GigaChat.** Чат-виджет с tool-calling по данным платформы (только чтение), бюджетами токенов и rate-limit.
- **Чат поддержки.** Виджет для авторизованных пользователей и гостей с real-time доставкой через SSE.
- **Ролевой доступ.** Четыре роли (`admin`, `devrel`, `speaker`, `guest`), регистрация по инвайту, аудит действий, блокировка при брутфорсе.

---

## 🛠 Технологический стек

- **Backend:** Python 3.12, Django 6.0
- **База данных:** PostgreSQL (16 в Docker)
- **Фронтенд:** Django Templates + ванильный JS, лёгкая SPA-навигация, Chart.js, тёмная/светлая тема
- **AI:** GigaChat (SberDevices) через пакет `gigachat`
- **Парсинг:** `requests` + `beautifulsoup4` (Highload++)
- **Хранилище медиа:** локальное `MEDIA_ROOT` или S3-совместимое (Cloudflare R2) через `django-storages`
- **Статика:** WhiteNoise
- **Деплой:** Docker + docker-compose, Gunicorn
- **Архитектура:** модульный монолит (4 Django-приложения)

Полный список — в [`requirements.txt`](requirements.txt).

---

## 🧩 Приложения

| Приложение | Назначение |
|------------|------------|
| **`starlift`** | Домен: модели Speaker / Event / Feedback и сопутствующие, страницы и JSON API, аналитика, метрики главной, QR, кабинет спикера (`views_me`) |
| **`accounts`** | Аутентификация: роли, инвайты, верификация email, блокировки, аудит, профиль, консоль администратора/DevRel, заявки спикеров |
| **`assistant`** | AI-чат на GigaChat: agent-loop с tool-calling, SSE-стрим, бюджеты токенов, rate-limit |
| **`support`** | Чат поддержки: тикеты, сообщения, real-time через SSE; отдельный контур для гостей по токену |

Детали — в [docs/architecture.md](docs/architecture.md).

---

## 🚀 Быстрый старт

### Вариант A — Docker (рекомендуется)

```bash
# 1. Подготовьте production-окружение
cp starlift/.env.example starlift/.env.production
# отредактируйте DB_*, SECRET_KEY, GIGACHAT_* и т.д.

# 2. Поднимите стек (Postgres + web + парсер)
docker compose up -d --build

# 3. Создайте администратора
docker compose exec web python manage.py createsuperuser
```

Веб доступен на `http://127.0.0.1:8000`. Контейнер `web` сам прогоняет миграции и `collectstatic` (см. `entrypoint.sh`, переменная `RUN_MIGRATIONS=true`).

### Вариант B — локально

```bash
cd starlift
python -m venv ../.venv && ../.venv/Scripts/activate   # Windows
# source ../.venv/bin/activate                          # Linux/macOS
pip install -r ../requirements.txt

cp .env.example .env          # пропишите DB_* и при необходимости GIGACHAT_*
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Полная инструкция (требования, переменные окружения, object storage, production-чеклист) — в [docs/setup.md](docs/setup.md).

---

## ⚙️ Частые команды

Все команды выполняются из каталога `starlift/`.

```bash
# Разработка
python manage.py runserver
python manage.py makemigrations && python manage.py migrate

# Парсер Highload++
python manage.py sync_highload --once                  # один проход
python manage.py sync_highload --interval-minutes 30   # цикл

# Обслуживание
python manage.py cleanup_stale_auth --dry-run          # очистка устаревших токенов/попыток
python manage.py seed_demo_feedbacks                   # демо-отзывы
python manage.py migrate_avatars_to_object_storage --dry-run

# Тесты
python manage.py test accounts     # auth, инвайты, lockout, профиль
python manage.py test starlift     # модели, парсер, NPS, кабинет, дедлайны
python manage.py test assistant    # AI-ассистент
python manage.py test              # всё
```

---

## 🧪 Тесты

Покрытие включает: валидаторы и политику паролей, backend логина, блокировку при брутфорсе, токены и аудит, flow логина / сброса / смены пароля, инвайты (создание / отзыв / приём), профиль и смену email, консоль (привязка спикера, разблокировка, смена роли); парсинг Highload++ и импорт без дублей, команду `sync_highload`; модели и расчёт NPS, кабинет спикера, дедлайны и self-submission мероприятий, дашборд главной; инструменты и agent-loop AI-ассистента.

```bash
cd starlift
python manage.py test
```

---

## 📂 Структура репозитория (кратко)

```
project-verison1/
├── README.md                # этот файл
├── CLAUDE.md                # заметки для AI-ассистента разработки
├── requirements.txt
├── Dockerfile / docker-compose.yml / entrypoint.sh
├── docs/                    # подробная документация (см. таблицу выше)
└── starlift/                # корень Django (рядом manage.py)
    ├── manage.py
    ├── starlift/            # конфиг + домен (settings, urls, models, views, analytics…)
    ├── accounts/            # аутентификация, консоль, профиль
    ├── assistant/           # AI-ассистент (GigaChat)
    ├── support/             # чат поддержки
    ├── parser/              # Highload++ парсер
    ├── templates/           # общие HTML-шаблоны
    ├── static/ media/       # статика и загружаемые файлы
    └── */management/commands/   # sync_highload, cleanup_stale_auth, …
```

Подробная карта каталогов — в [docs/architecture.md](docs/architecture.md).

---

## 🔐 Безопасность

- Регистрация **только по приглашению** (или через заявку гостя на роль спикера с одобрением DevRel).
- Блокировка после 6 неудачных логинов за 60 секунд (настраивается).
- Аудит всех значимых действий в `AuditLog` (`/console/audit/`).
- Стандартные механизмы Django: CSRF, сессии, хеширование паролей, расширенная политика паролей.

Перед продакшеном обязательно: задайте свой `SECRET_KEY`, `DEBUG=False`, корректные `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS`, включите HTTPS. См. [docs/setup.md](docs/setup.md) и [docs/auth-roles.md](docs/auth-roles.md).

---

## 📄 Лицензия

Внутренний проект (MVP). Условия использования уточняйте у владельца репозитория.

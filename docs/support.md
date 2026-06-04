# Чат поддержки

Приложение `support` — встроенный чат обращений в поддержку. Как и ассистент, это **drawer-виджет** в `templates/base.html` без отдельных страниц; доставка сообщений в реальном времени — через **SSE**. Поддерживаются два контура: авторизованные пользователи и **гости** (по токену, без логина).

---

## 1. Модели (`support/models.py`)

### SupportTicket — обращение
- Автор: `author_kind` = `user` | `guest`. Для пользователя — `author_user`; для гостя — `guest_name`, `guest_email` и **`guest_token_hash`** (SHA-256 токена доступа к треду) + `guest_notified_at`.
- `subject`, `status` (`open`/`closed`), таймстемпы, `closed_at`.
- `last_message_at` / `last_message_sender_kind` — денормализация для сортировки и подсчёта непрочитанного.
- Свойство `author_label` — человекочитаемая подпись автора.

### SupportMessage — сообщение
- `ticket`, `sender_kind` (`user`/`admin`/`guest`/`system`), опц. `sender_user`, `body`, `created_at`.
- В `save()` при создании обновляет у тикета `last_message_at`, `last_message_sender_kind`, `updated_at` (одним `UPDATE`, без лишних запросов).

### SupportRead — отметки прочтения
`ticket` + `user` (`unique_together`) + `last_read_at`. Позволяет считать непрочитанное для «колокольчика» без сканирования всех сообщений — сравнением `ticket.last_message_at` с `last_read_at` и видом последнего отправителя.

---

## 2. Маршруты

### Авторизованные — `/assistant/support/…` (namespace `support`)

| Маршрут | Назначение |
|---------|------------|
| `POST t/<id>/send/` | Отправить сообщение |
| `POST t/<id>/typing/` | Сигнал «печатает» |
| `GET t/<id>/stream/` | **SSE-стрим** треда |
| `POST t/<id>/close/` | Закрыть тикет |
| `POST t/<id>/delete/` | Удалить тикет |
| `GET api/unread/` | Счётчик непрочитанного |
| `GET api/list/` | Список тикетов |
| `GET api/t/<id>/` | Сообщения тикета |
| `POST api/new/` | Создать тикет |

### Гости — `/support/…` (namespace `support_guest`)

| Маршрут | Назначение |
|---------|------------|
| `POST new/` | Создать обращение (имя, email, тема) → выдаётся токен |
| `GET t/<token>/` | Открыть тред по токену |
| `POST t/<token>/send/` | Отправить сообщение |
| `POST t/<token>/typing/` | Сигнал «печатает» |
| `GET t/<token>/stream/` | **SSE-стрим** треда |

Гость работает без логина — доступ к своему треду по токену (в БД хранится только его хэш).

---

## 3. Real-time (SSE)

Доставка сообщений и индикатора «печатает» идёт через Server-Sent Events (`support/views/stream.py`): клиент держит открытое соединение на `…/stream/`, сервер шлёт новые сообщения/события. Это не требует Redis/WebSocket — работает поверх обычного Django-ответа со стримом.

---

## 4. Лимиты (окружение)

| Переменная | Default | Назначение |
|------------|---------|------------|
| `SUPPORT_RATE_LIMIT_PER_USER` | `30` | Запросов на пользователя в окне |
| `SUPPORT_RATE_LIMIT_PER_GUEST` | `5` | Запросов на гостя в окне |
| `SUPPORT_RATE_LIMIT_WINDOW_SECONDS` | `300` | Длина окна (с) |

Rate-limit реализован поверх Django cache (как и у ассистента).

---

## 5. UI

FAB-виджет (drawer) в `templates/base.html`: для авторизованных — список обращений и тред с «колокольчиком» непрочитанного (на базе `SupportRead`); для гостя — форма создания обращения и тред по токену. Роль `admin`/`devrel` отвечает на обращения (отправитель `admin`), системные уведомления помечаются `sender_kind=system`.

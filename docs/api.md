# Маршруты: страницы, API и SSE

Корневой роутер — `starlift/urls.py`; аутентификация — `accounts/urls.py` (префиксы `/auth/`, `/profile/`, `/console/`, `/application/`); ассистент — `assistant/urls.py`; поддержка — `support/urls.py` и `support/urls_guest.py`.

Условные обозначения доступа: **public** — без логина; **member** — `member_required` (admin/devrel/speaker); **admin** — `role_required('admin')`; **speaker** — `speaker_required` (роль speaker + привязанная карточка); **staff** — admin/devrel (консоль).

---

## 1. Домен `starlift`

### 1.1 HTML-страницы

| Маршрут | View | Доступ | Назначение |
|---------|------|--------|------------|
| `/` , `/index/` | `index_view` | member | Главный дашборд (оперативный центр) |
| `/explore/` | `explore_view` | login | Гостевой лендинг (агрегаты без PII) |
| `/speakers/` | `speakers_view` | member | Каталог спикеров |
| `/events/` | `events_view` | member | Лента мероприятий |
| `/analytics/` | `analytics_view` | member | Аналитика, графики, кандидаты |
| `/speakers/add/` | `speaker_add` | admin | Создать спикера |
| `/speakers/edit/<pk>/` | `speaker_edit` | admin | Редактировать спикера |
| `/speakers/delete/<pk>/` | `speaker_delete` | admin | Удалить спикера |
| `/qr-generator/` | `qr_generator_view` | member | Выбор пары спикер↔событие для QR |
| `/speaker/<sid>/event/<eid>/qr/` | `generate_qr_view` | member | Страница QR |
| `/speaker/<sid>/event/<eid>/qr/poster.png` | `qr_poster_view` | member | Печатный PNG-постер |
| `/rate/<event_id>/<speaker_id>/` | `submit_feedback_view` | **public** | Форма оценки выступления (0–10) |
| `/thanks/` | `thank_you_view` | public | Страница благодарности |

### 1.2 JSON API

| Маршрут | View | Доступ | Возвращает |
|---------|------|--------|------------|
| `GET /api/speakers/` | `speakers_api` | member | Спикеры с событиями и отзывами |
| `GET /api/events/` | `events_api` | member | События со спикерами |
| `GET /api/home/` | `home_api` | member | Агрегаты главной (KPI, ближайшие, топ/ваши события, активность) |
| `POST /api/speakers/<id>/like/` | `speaker_like_toggle` | member | Переключить избранное |
| `POST /api/speakers/<id>/recommend/` | `speaker_recommend_toggle` | staff | Переключить флаг «Рекомендую» |
| `GET /api/notifications/` | `notifications_api` | member | Уведомления (заявки, приглашения, верификации) |
| `GET /api/my-event-requests/` | `my_event_requests_api` | speaker | Заявки текущего спикера |
| `GET /api/admin/pending-requests/` | `admin_pending_requests_api` | staff | Заявки на рассмотрении |
| `POST /api/admin/quick-approve/<request_id>/` | `admin_quick_approve` | staff | Быстрое одобрение заявки |

`/api/home/` отдаёт `version`-хэш; фронт поллит эндпоинт каждые 15 с и перерисовывается только при смене версии. Состав ответа зависит от роли: топ спикеров и лента активности — для admin/devrel, блок «Ваши мероприятия» — для спикера.

### 1.3 Заявки и события (формы)

| Маршрут | View | Доступ |
|---------|------|--------|
| `POST /events/request-create/` | `submit_event_request_view` | speaker |
| `POST /events/<event_id>/request-join/` | `submit_join_request_view` | speaker |
| `POST /events/admin/create/` | `admin_event_create` | staff |
| `POST /events/admin/<event_id>/edit/` | `admin_event_edit` | staff |
| `POST /events/admin/<event_id>/delete/` | `admin_event_delete` | staff |
| `POST /events/admin/<event_id>/remove-speaker/<speaker_id>/` | `admin_event_remove_speaker` | staff |

---

## 2. Личный кабинет спикера (`/me/…`)

Все маршруты — `speaker_required` (роль speaker + привязанная карточка). View — `starlift/views_me.py`.

| Маршрут | Назначение |
|---------|------------|
| `/me/` | Дашборд кабинета |
| `/me/feedback/` | Свои отзывы |
| `/me/feedback/export.csv` | Экспорт отзывов в CSV |
| `/me/events/` | Свои мероприятия (предстоящие + прошедшие) |
| `/me/events/upload/` | Загрузить прошедшее мероприятие (self-submit → pending) |
| `/me/events/<pk>/edit/` , `/me/events/<pk>/delete/` | Правка/удаление своей неверифицированной заявки |
| `/me/events/<event_id>/rate/` | Самооценка прошедшего события |
| `/me/requests/` | Свои заявки |
| `/me/invitations/` | Приглашения от DevRel |
| `/me/invitations/<id>/accept/` , `/decline/` | Ответ на приглашение |
| `/me/favorites/` | Избранные спикеры |

---

## 3. Аутентификация и консоль (`accounts`, namespace `accounts:`)

### 3.1 Аутентификация (public/anonymous)

| Маршрут | Назначение |
|---------|------------|
| `/auth/login/` , `/auth/logout/` | Вход (по username или email) / выход |
| `/auth/register/` , `/auth/register/pending/` | Регистрация и экран ожидания |
| `/auth/password-reset/…` | Сброс пароля (запрос, done, confirm, complete) |
| `/auth/password-change/…` | Смена пароля |
| `/auth/email/verify/<token>/` | Верификация email |
| `/auth/invite/<token>/` | Приём инвайта (регистрация по приглашению) |

### 3.2 Профиль (login)

`/profile/` — профиль и аватар; `/profile/email/` — смена email (с подтверждением); `/profile/email/cancel/` — отмена.

### 3.3 Консоль (staff: admin/devrel)

| Маршрут | Назначение |
|---------|------------|
| `/console/` , `/console/users/` | Пользователи |
| `/console/users/<user_id>/` | Карточка пользователя (роль, разблокировка, привязка спикера) |
| `/console/invites/` , `/console/invites/<uuid>/revoke/` | Инвайты: список и отзыв |
| `/console/audit/` | Журнал аудита |
| `/console/event-requests/` , `/console/event-requests/<id>/<action>/` | Заявки на события (approve/reject) |
| `/console/events/<event_id>/invite/` | Пригласить спикера на событие |
| `/console/event-invitations/<id>/cancel/` | Отменить приглашение |
| `/console/speaker-applications/<id>/` , `/<id>/<action>/` | Заявки гостей на роль спикера |
| `/console/speaker-events/<event_id>/` , `/<event_id>/<action>/` | Верификация self-submitted событий |

### 3.4 Заявка на роль спикера (гость)

`/application/` — форма заявки; `/application/pending/` — экран ожидания.

---

## 4. AI-ассистент (`assistant`, drawer-only)

Страничных маршрутов нет — это backend для FAB-виджета в `base.html`.

| Маршрут | Назначение |
|---------|------------|
| `GET /assistant/state/` | Состояние: последние беседы, активная беседа |
| `POST /assistant/clear/` | Очистить/архивировать |
| `POST /assistant/conversations/` | Создать беседу |
| `POST /assistant/c/<id>/send/` | Отправить сообщение |
| `GET /assistant/c/<id>/stream/` | **SSE-стрим** ответа (delta / tool_start / tool_end / done / error) |

См. [assistant.md](assistant.md).

---

## 5. Поддержка (`support`, drawer-only)

### Авторизованные (`/assistant/support/…`, namespace `support`)

`POST t/<id>/send/`, `POST t/<id>/typing/`, `GET t/<id>/stream/` (**SSE**), `POST t/<id>/close/`, `POST t/<id>/delete/`; JSON: `api/unread/`, `api/list/`, `api/t/<id>/`, `api/new/`.

### Гости (`/support/…`, namespace `support_guest`)

`POST new/`, `GET t/<token>/`, `POST t/<token>/send/`, `POST t/<token>/typing/`, `GET t/<token>/stream/` (**SSE**) — доступ по токену тикета без логина.

См. [support.md](support.md).

---

## 6. Прочее

- `/admin/` — стандартная админка Django.
- Медиа (`MEDIA_URL`): в `DEBUG` отдаётся `django.conf.urls.static`; в проде без object storage — через `static_serve` (см. конец `starlift/urls.py`). При object storage медиа идёт напрямую с бакета.

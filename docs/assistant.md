# AI-ассистент (GigaChat)

Приложение `assistant` — чат на **GigaChat** (SberDevices) с историей бесед в БД и tool-calling по данным платформы (только чтение). Это **drawer-виджет** (FAB) в `templates/base.html` без отдельных страниц; общение с бэкендом — через JSON + **SSE-стрим**.

---

## 1. Из чего состоит

```
assistant/
├── models.py                 # Conversation, Message
├── agent/
│   ├── loop.py               # agent-loop: генератор AgentEvent (delta/tool_start/tool_end/done/error)
│   ├── gigachat_client.py    # единственное место, знающее про GigaChat
│   ├── budget.py             # бюджеты токенов (беседа / пользователь-день / глобально)
│   └── tools/                # инструменты: speakers.py, events.py, analytics.py
├── services/                 # rate_limit и пр.
├── views/
│   ├── chat.py               # send_message + SSE stream
│   └── conversations.py      # state / create / clear
└── tests/                    # включая fakes.FakeGigaChatClient
```

---

## 2. Agent-loop

`assistant/agent/loop.py` — генератор, возвращающий `AgentEvent(kind, payload)`:

| kind | Когда |
|------|-------|
| `delta` | Кусок текста ответа |
| `tool_start` | Модель вызвала инструмент |
| `tool_end` | Инструмент вернул результат |
| `done` | Ответ завершён |
| `error` | Ошибка (в т.ч. ошибка провайдера) |

Слой view (`views/chat.py`) превращает эти события в **Server-Sent Events** для браузера. Цикл «модель → инструмент → модель» ограничен `ASSISTANT_MAX_TOOL_ITERATIONS` (по умолчанию 8), чтобы не зациклиться.

---

## 3. Инструменты (read-only)

Каждый модуль в `agent/tools/` регистрирует функции декоратором `@assistant_tool(name, description, parameters)`. Декоратор обрезает результат до `ASSISTANT_TOOL_RESULT_MAX_BYTES` (по умолчанию 4 КБ). Встроенные инструменты:

| Инструмент | Назначение |
|------------|------------|
| `search_speakers` | Поиск спикеров |
| `get_speaker_profile` | Профиль спикера |
| `find_events` | Поиск мероприятий |
| `get_event_details` | Детали мероприятия |
| `nps_summary` | Сводка по NPS/оценкам |

**Изоляция данных по ролям:** спикер видит только свои данные — это обеспечивается фильтрами в queryset инструментов, **не** в промптах.

---

## 4. Изоляция провайдера

`assistant/agent/gigachat_client.py` — единственное место, знающее о GigaChat. В тестах подставляется `assistant/tests/fakes.FakeGigaChatClient` со сценарными ответами. Смена LLM-провайдера = правка одного файла.

---

## 5. Бюджеты токенов и лимиты

`assistant/agent/budget.py` — несколько уровней ограничений:

| Уровень | Настройка | Default |
|---------|-----------|---------|
| На беседу | `ASSISTANT_MAX_TOKENS_PER_CONVERSATION` | 200000 |
| На пользователя в день (admin) | `ASSISTANT_DAILY_TOKEN_BUDGET_ADMIN` | 500000 |
| На пользователя в день (speaker) | `ASSISTANT_DAILY_TOKEN_BUDGET_SPEAKER` | 100000 |
| Глобально в день | `ASSISTANT_DAILY_GLOBAL_BUDGET` | 2000000 |
| Выход за ход | `ASSISTANT_MAX_OUTPUT_TOKENS_PER_TURN` | 1500 |
| Вход за ход | `ASSISTANT_MAX_INPUT_TOKENS_PER_TURN` | 12000 |
| На одно сообщение пользователя | `ASSISTANT_MAX_TOKENS_PER_USER_MESSAGE` | 25000 |

Поведение при исчерпании дневного бюджета — `ASSISTANT_DAILY_BUDGET_ACTION` (`warn` по умолчанию). Контекст беседы ограничен `ASSISTANT_CONTEXT_HISTORY_MESSAGES` (20) и `ASSISTANT_CONTEXT_TOOL_RESULTS_MESSAGES` (5).

**Rate-limit** (`assistant/services/rate_limit.py`) — скользящее окно на Django cache: `ASSISTANT_RATE_LIMIT_PER_USER` (30) запросов за `ASSISTANT_RATE_LIMIT_WINDOW_SECONDS` (900 c).

---

## 6. Конфигурация (окружение)

| Переменная | Default | Назначение |
|------------|---------|------------|
| `ASSISTANT_ENABLED` | `true` | Включение ассистента |
| `GIGACHAT_AUTH_KEY` | — | Ключ авторизации GigaChat (**обязателен** для работы LLM) |
| `GIGACHAT_SCOPE` | `GIGACHAT_API_PERS` | Scope доступа |
| `GIGACHAT_MODEL` | `GigaChat-Pro` | Модель |
| `GIGACHAT_VERIFY_SSL` | `false` | Проверка SSL при обращении к API |
| `ASSISTANT_*` | см. таблицу выше | Бюджеты, лимиты, контекст |

Без `GIGACHAT_AUTH_KEY` UI доступен, но обращения к модели завершатся ошибкой провайдера (событие `error` в стриме).

---

## 7. Маршруты и UI

| Маршрут | Назначение |
|---------|------------|
| `GET /assistant/state/` | Последние беседы и активная беседа |
| `POST /assistant/conversations/` | Создать беседу |
| `POST /assistant/c/<id>/send/` | Отправить сообщение |
| `GET /assistant/c/<id>/stream/` | SSE-стрим ответа |
| `POST /assistant/clear/` | Очистка/архив |

UI — FAB-виджет (drawer) в `templates/base.html` со списком бесед и тредом сообщений, в стилистике Sber (`--sber-green`, `--light-green` и пр.). Истории — `Conversation`/`Message`, токены учитываются в полях `token_in`/`token_out` каждого сообщения.

---

## 8. Тесты

```bash
cd starlift
python manage.py test assistant
```

Покрывают инструменты, agent-loop, view-слой и бюджеты с подставным `FakeGigaChatClient` (реальные вызовы GigaChat в тестах не выполняются).

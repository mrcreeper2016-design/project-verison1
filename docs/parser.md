# Парсер Highload++

Пакет `parser/` собирает доклады и спикеров со страниц **Highload++** (`highload.ru`) и пишет их **напрямую в PostgreSQL** через ORM (`Speaker`, `Event`, M2M-связь). Промежуточных CSV нет.

- `parser/highload.py` — разбор HTML (BeautifulSoup) в структурированные записи.
- `parser/highload_importer.py` — запись записей в БД с дедупликацией.
- `starlift/management/commands/sync_highload.py` — management-команда (разовый проход или цикл).
- `parser/tavily_parser.py` — вспомогательная интеграция (необязательный контур, не подключён к `sync_highload`).

---

## 1. Команда `sync_highload`

```bash
cd starlift

# Разовый проход
python manage.py sync_highload --once

# Цикл с паузой (по умолчанию 30 мин или HIGHLOAD_INTERVAL_MINUTES)
python manage.py sync_highload --interval-minutes 30

# Ограничить число проходов (удобно для отладки/тестов)
python manage.py sync_highload --interval-minutes 5 --max-cycles 3
```

| Флаг | Назначение |
|------|------------|
| `--once` | Один проход и выход |
| `--interval-minutes N` | Пауза между проходами (игнорируется с `--once`); по умолчанию `HIGHLOAD_INTERVAL_MINUTES` или 30 |
| `--max-cycles N` | Остановиться после N проходов; без флага и без `--once` — бесконечно |

В `docker-compose.yml` для этого выделен отдельный сервис `parser`, запускающий цикл с интервалом 30 минут.

---

## 2. Конфигурация (окружение)

| Переменная | Default | Назначение |
|------------|---------|------------|
| `HIGHLOAD_URLS` | — | Список URL страниц с тезисами через запятую |
| `HIGHLOAD_INTERVAL_MINUTES` | `30` | Интервал цикла |
| `HIGHLOAD_REQUEST_TIMEOUT` | `20` | Таймаут HTTP-запроса (с) |
| `HIGHLOAD_MAX_RETRIES` | `3` | Число повторов при сбое запроса |

Пример:

```dotenv
HIGHLOAD_URLS=https://highload.ru/moscow/2025/abstracts,https://highload.ru/spb/2026/abstracts
HIGHLOAD_INTERVAL_MINUTES=30
HIGHLOAD_REQUEST_TIMEOUT=20
HIGHLOAD_MAX_RETRIES=3
```

Секретов парсер не требует.

---

## 3. Логика импорта

Один проход (`run_import_pass`) по каждому URL:

1. **Загрузка HTML** с повторами (`retry_call`, до `HIGHLOAD_MAX_RETRIES`) и таймаутом.
2. **Парсинг** страницы в записи (автор, компания, стек, заголовок доклада, дата, ссылка) — `parser.highload.parse_records_from_html`.
3. **Дедупликация и запись** каждой записи (`import_parsed_row`):
   - спикер ищется по нормализованному имени + компании/стеку (`find_speaker`); при отсутствии — создаётся;
   - событие ищется по ссылке/заголовку/дате (`find_event`); при отсутствии — создаётся с `source="parser"`;
   - связь спикер↔событие добавляется в M2M, если её ещё нет;
   - неполные/пустые записи пропускаются (увеличивают счётчик `skipped`).
4. **Счётчики** (`ImportCounters`): `parsed / inserted / updated / skipped / failed` — пишутся в лог в конце прохода.

Запись идёт **по одному событию в транзакции**; частичные сбои не откатывают весь проход.

---

## 4. Эксплуатация

- Логи прохода (`highload import pass: parsed=… inserted=… updated=… skipped=… failed=…`) полезно мониторить.
- События с `source="parser"` визуально отделяются от внутренних/самовыдвинутых в интерфейсе и аналитике.
- Парсер зависит от вёрстки внешнего сайта — при изменениях на `highload.ru` может потребоваться правка `parser/highload.py`.

См. также общий поток данных в [architecture.md](architecture.md#7-потоки-данных).

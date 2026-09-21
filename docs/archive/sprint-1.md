# Sprint 1 — Надёжность gateway и RAG (2 недели)

**Окно:** 2 недели · **Состав:** 1 разработчик · **Базовые чеки:** `python scripts/check_all.py --quick` перед каждым коммитом; ruff 0, mypy 0.

## Прогресс

- [x] RAVEN-107 — `raven benchmark` CLI (done)
- [x] RAVEN-103 — WS reconnect jitter (done)
- [x] RAVEN-101 — FlowSession persistence (done)
- [x] RAVEN-102 — SSE live-обновления сессий (done)
- [x] RAVEN-104 — Monitor SLO / aggregation / adaptive interval (done)
- [x] RAVEN-105 — RAG hybrid search + кэш эмбеддингов (done)
- [x] RAVEN-106 — RBAC на уровне инструментов (done)

> Роадмап сверен с кодом: часть его пунктов уже реализована (git/test/db-инструменты, rate limiting, prometheus `/api/metrics/prometheus`, exponential backoff в `web/src/hooks/useWebSocket.ts:30`, multi-agent). Спринт строится только на подтверждённых пробелах.

**Цель спринта:** состояние gateway перестаёт теряться при рестарте; дашборд получает live-обновления сессий; мониторинг и RAG получают недостающие SLO/aggregation/hybrid-search; появляется RBAC на уровне инструментов и бенчмарк-CLI.

---

## Определение Done (применимо ко всем задачам)

- [ ] `python -m ruff check <изменённые файлы>` — 0 ошибок
- [ ] `python -m mypy <изменённые файлы>` — 0 ошибок
- [ ] Новые функции покрыты юнит-тестами (pytest), тесты проходят
- [ ] Type hints для всех функций (AGENTS.md)
- [ ] `loguru`, никаких `print`; асинхронные I/O (AGENTS.md)
- [ ] Если затронут `web/`: `npx tsc --noEmit` 0, `npx vitest run`, `npx vite build` — зелёные

---

## RAVEN-101 — Персистентность FlowSession (1.5 дня)

**Labels:** `backend`, `gateway`, `reliability` · **Estimate:** 1.5d

**Контекст:** `FlowSession` (`raven/gateway/daemon.py:49`) — dataclass, живёт только в `self.sessions` (`daemon.py:74`). После рестарта daemon все сессии теряются.

**Задачи:**
- `FlowSession.to_dict()` / `FlowSession.from_dict()` (без сериализации `ReActAgent`/`_task` — только id, channel, created_at, message_count, status).
- `SessionStore` — JSON-файлы в `data/sessions/*.json` (путь из `settings.resolved_data_dir`), `save()`/`load_all()`/`remove()`.
- Писать на каждое сообщение через batched flush каждые 5s (`asyncio.create_task` + `asyncio.Event`/timer в `RavenFlowDaemon`), flush на `shutdown`.
- На старте: сканировать `data/sessions/`, восстанавливать с `status="resumed"`; мёртвые записи (`resumed` > N часов) удалять.
- Graceful shutdown: на `CancelledError`/`KeyboardInterrupt` — `await store.flush()`, таймаут 5s.

**Acceptance criteria:**
- Создали сессию → рестарт daemon → сессия видна с `status="resumed"` и сохранённым `message_count`.
- Нет потери данных при `Ctrl+C` во время активной сессии.
- `data/sessions/` не растёт бесконечно (удаление просроченных).

**Tests:** `tests/gateway/test_session_store.py` — round-trip, восстановление, удаление просроченных, batched flush.

**Verification:** `python -m pytest tests/gateway/test_session_store.py -q`

---

## RAVEN-102 — SSE live-обновления сессий (1 день)

**Labels:** `backend`, `api`, `realtime` · **Estimate:** 1d

**Контекст:** `SessionInfo` (`daemon.py:34`) не отправляется в UI. Инфраструктура SSE уже есть — `raven/core/sse.py`.

**Задачи:**
- Эндпоинт `GET /events/sessions` (SSE) на `api_app` gateway: при создании/обновлении/закрытии `FlowSession` отправлять `SessionInfo` event.
- Подключить к событиям `daemon.py` (публикация через общий `SSEHub` из `sse.py`).
- Фронт: в `web/src/pages/Dashboard.tsx` (или `Layout.tsx`) подписка на `EventSource("/events/sessions")` + рендер списка активных сессий; авторизация через Bearer-токен в query (`?token=...`).
- Закрывать соединение на unmount.

**Acceptance criteria:**
- В дашборде появляется живой список сессий без перезагрузки страницы.
- EventSource корректно закрывается при уходе со страницы (нет утечки соединений).

**Tests:** `tests/core/test_sse.py` — эмиссия события, payload `SessionInfo`, закрытие соединения.

**Verification:** `python -m pytest tests/core/test_sse.py -q` + `npx tsc --noEmit`

---

## RAVEN-103 — WS reconnect: jitter + тест (0.5 дня)

**Labels:** `frontend`, `realtime` · **Estimate:** 0.5d

**Контекст:** exponential backoff уже есть (`web/src/hooks/useWebSocket.ts:30`), но без jitter — при одновременном реконнекте многих клиентов gateway получает синхронный шквал.

**Задачи:**
- Добавить jitter ±30% к `delay` на строке 30: `Math.round(delay * (0.85 + Math.random() * 0.3))`.
- Вынести расчёт задержки в чистую функцию `computeReconnectDelay(attempt, base=1000, cap=30000)` для тестируемости.

**Acceptance criteria:**
- Задержка всегда в диапазоне `[0.85*exp, 1.15*exp]` и не превышает 30s.
- При `attempt=0` задержка ≤ ~1.15s.

**Tests:** `web/src/hooks/useWebSocket.test.ts` — монотонный рост, кап 30s, jitter в пределах диапазона.

**Verification:** `npx vitest run src/hooks/useWebSocket.test.ts`

---

## RAVEN-104 — Monitor v1.5: SLO, aggregation, adaptive interval (2.5 дня)

**Labels:** `backend`, `monitoring` · **Estimate:** 2.5d

**Контекст:** `raven/core/monitor/{engine,store,alert,models,conditions}.py`. Есть 4 чекера (`raven/core/monitor/checkers/`). Нет SLO, агрегации алертов и адаптивного интервала.

**Задачи:**
- `SLO` в `models.py`: `target` (e.g. 0.999), `window`; расчёт `error_budget` из `monitor_checks` в `store.py` (SQL-агрегация ok/fail за окно).
- Алерт-агрегация в `alert.py`: группировка по `(monitor.group, code)` — одна ошибка × N мониторов = 1 уведомление + счётчик затронутых.
- Adaptive interval в `engine.py`: после 3 подряд failed — увеличить интервал ×2 (до cap, e.g. 3600s), после восстановления вернуть к базовому; поле `effective_interval` в статусе монитора.
- В `Alert` добавить `group`; эндпоинт `GET /api/monitor/slo` → бюджет по каждому монитору.

**Acceptance criteria:**
- Error budget рассчитывается из истории проверок; при исчерпании монитор помечается `slo_breached`.
- 10 фейлящих мониторов одной группы → одно уведомление (не 10).
- Интервал растёт при деградации и сбрасывается при восстановлении.

**Tests:** `tests/core/test_monitor_slo.py` — расчёт бюджета, агрегация, адаптивный интервал.

**Verification:** `python -m pytest tests/core/test_monitor_slo.py -q`

---

## RAVEN-105 — RAG hybrid search + кэш эмбеддингов (2 дня)

**Labels:** `backend`, `rag` · **Estimate:** 2d

**Контекст:** `raven/core/rag/retriever.py` (`Retriever.retrieve`, строка 68) — только семантический поиск; `vector_store.py` хранит векторы без кэша.

**Задачи:**
- Lexical-скор: лёгкий BM25 (без внешних зависимостей — считаем вручную, `k1=1.5, b=0.75`) по чанкам в `vector_store.py` или отдельном модуле `bm25.py`.
- Гибридный поиск в `retriever.retrieve()`: `score = w*cosine + (1-w)*bm25`, `w=0.7` по умолчанию, параметр `search_mode: "hybrid"|"semantic"|"lexical"`.
- Кэш эмбеддингов: `data/cache/embeddings_cache.json` — ключ MD5(chunk text) → vector; при индексации пропускать уже известные тексты.
- Метрики: вернуть `scores` в результатах для диагностики.

**Acceptance criteria:**
- Гибридный режим на запросе с точным термином ранжирует выше, чем чистый семантический (тест на фикстурных чанках).
- Повторная индексация того же текста не вызывает повторного вызова embedder (счётчик вызовов = 1).
- Кэш корректно персистится между запусками.

**Tests:** `tests/core/test_rag_hybrid.py` — BM25-скор, гибридное ранжирование, кэш hit/miss.

**Verification:** `python -m pytest tests/core/test_rag_hybrid.py -q`

---

## RAVEN-106 — RBAC на уровне инструментов (2 дня)

**Labels:** `backend`, `security` · **Estimate:** 2d

**Контекст:** исполнение идёт через `_run_handler` (`raven/core/task_engine/tool_registry.py:125`); JWT уже несёт `role` (`daemon.py:98`).

**Задачи:**
- `ToolSpec.dangerous: bool = False` и поле `allowed_roles: list[str] | None` в `raven/tools/*` для опасных тулов (например `db_query` → `["admin"]`, `shell` → `["admin","developer"]`).
- Проверка в `_run_handler`: роль из контекста вызова → `denied` с информативным сообщением `[error: tool requires role ...]`.
- `GET/POST /api/tools/policy` — просмотр/изменение маппинга роль→тул (persist в `data/tool_policy.json`).
- Фронт (по желанию): секция в `Settings.tsx`.

**Acceptance criteria:**
- Вызов запрещённого тула возвращает `[error: ...]`, а не исполняется.
- Политику можно переопределить через API без рестарта.
- По умолчанию поведение не ломает существующие роли (`user`/`admin`).

**Tests:** `tests/core/test_tool_rbac.py` — allow/deny по ролям, дефолтные роли, переопределение политики.

**Verification:** `python -m pytest tests/core/test_tool_rbac.py -q`

---

## RAVEN-107 — Quick win: `raven benchmark` (1 день)

**Labels:** `cli`, `perf` · **Estimate:** 1d

**Контекст:** бенчмарк-команды нет (проверено: `raven/cli/` не содержит benchmark).

**Задачи:**
- `raven/cli/benchmark_cmd.py` — micro-бенчмарки: `file_read` (1MB), `shell` echo, `db_query` (SELECT), LLM `complete()` latency.
- Замеры: p50/p95/p99 (своя реализация перцентилей, без новых зависимостей), через `asyncio` + `time.perf_counter`.
- Вывод таблицы в CLI; `--iterations N` (default 20), `--json` для CI.
- Зарегистрировать в `raven/cli/main.py` (как `init`/`deploy`).

**Acceptance criteria:**
- `python -m raven benchmark` работает без LLM-ключа (LLM-секция скипается с пометкой).
- `--json` отдаёт машиночитаемый результат с p50/p95/p99.

**Tests:** `tests/cli/test_benchmark_cmd.py` — парсинг флагов, расчёт перцентилей, JSON-вывод.

**Verification:** `python -m pytest tests/cli/test_benchmark_cmd.py -q`

---

## Порядок и зависимости

```
RAVEN-107 (benchmark)   — независимый, можно начать первым (быстрая победа)
RAVEN-103 (jitter)      — независимый, 0.5 дня
RAVEN-101 (persistence) — блокирует RAVEN-102
RAVEN-102 (SSE)         — зависит от 101 (живые статусы из persisted-сессий)
RAVEN-104 (monitor)     — независимый
RAVEN-105 (RAG)         — независимый
RAVEN-106 (RBAC)        — независимый
```

Предлагаемый порядок: **107 → 103 → 101 → 102 → 104 → 105 → 106** (тяжёлые/зависимые — в середине, независимые бэкенд-задачи — параллельно).

## Риски

- **RAVEN-101:** бэкенд `ReActAgent` не сериализуем — в `to_dict` не включаем `agent`, при restore создаём новый `ReActAgent` с тем же `session_id` (проверить, что `get_session_manager` в `ravencode/runtime/multisession.py` умеет восстановить контекст).
- **RAVEN-106:** изменение `_run_handler` затрагивает все вызовы — прогонять полный набор `tests/core/test_tool_registry*.py` до/после.
- **RAVEN-105:** ручной BM25 должен совпадать по смыслу с гипотезами бенчмарка — зафиксировать тест-кейсы на реальных чанках кода.

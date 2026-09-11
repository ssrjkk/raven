<div align="center">
  <h1>Raven AI</h1>
  <p><i>2 в 1: <b>RavenCode</b> (аналог opencode — автономный coding-агент) + <b>RavenFlow</b> (аналог openclaw — персистентный workflow gateway). 25+ каналов. Задачи. Мониторы. RAG. Голос. Веб-дашборд.</i></p>

  <a href="#features">Возможности</a> •
  <a href="#quickstart">Быстрый старт</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">Архитектура</a> •
  <a href="#tech-stack">Технологии</a> •
  <a href="#license">Лицензия</a>

  [![CI](https://img.shields.io/github/actions/workflow/status/ssrjkk/raven/ci.yml?branch=main&label=CI&logo=github)]()
  [![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white)]()
  [![License](https://img.shields.io/badge/license-MIT-green)]()
  [![Channels](https://img.shields.io/badge/channels-25+-8A2BE2)]()
  [![RavenFlow](https://img.shields.io/badge/ravenflow-daemon-blue)]()
  [![RavenCode](https://img.shields.io/badge/ravencode-agent-purple)]()
  [![Tests](https://img.shields.io/badge/tests-4593%2B_passing-brightgreen)]()
  [![Coverage](https://img.shields.io/codecov/c/github/ssrjkk/raven?logo=codecov)]()
  [![Security](https://img.shields.io/badge/security-hardened-blueviolet)]()
  [![AI-OS-MVP](https://img.shields.io/badge/aios-mvp-purple)]()
  [![Hybrid](https://img.shields.io/badge/hybrid-web+api+desktop-orange)]()

  [English](README.md) •
  [Русский](README.ru.md) •
  [简体中文](README.zh.md) •
  [한국어](README.ko.md) •
  [Español](README.es.md) •
  [日本語](README.ja.md) •
</div>

<p align="center">
  <img src="https://img.shields.io/badge/status-active--development-brightgreen" alt="Status">
  <img src="https://img.shields.io/github/stars/ssrjkk/raven?style=social" alt="Stars">
</p>

---

## Demo

<p align="center">
  <i>📺 Посмотрите Raven в действии (30-секундное демо-GIF — скоро)</i>
</p>

```text
$ raven "объясни этот кодбаз и исправь падающий тест"
🐦 Raven анализирует ваш проект...
   → LSP-обогащение: обнаружено 3 языка
   → Планирование сессии отладки...
   → Запуск pytest — найдён 1 провал
   → Исправление assert в test_users.py
   → PR открыт: #42

$ raven
🐦 Интерактивный REPL — введите задачу или /help
  >
```

---

## Почему Raven AI?

**Raven AI** — это не просто бот. Это полноценный автоматизированный AI-ассистент уровня enterprise, работающий 24/7 на вашем сервере.

Он думает. Он планирует. Он действует. Он говорит. Он работает как поток.

- **Общается в 25+ каналах** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, веб-чат + ещё 15
- **RavenCode агент** — автономный coding-агент (`ravencode`) с LSP-авто-обогащением, параллельными мультисессиями, режимами plan/safe/fast, 30+ инструментами
- **RavenFlow gateway** — персистентный workflow-демон (`ravenflow`) с multi-agent роутингом, WebSocket-стримингом, управлением сессиями
- **Canvas визуальное пространство** — рендер rich-компонентов (код, таблицы, mermaid-диаграммы, изображения, алерты) в терминале или браузере
- **Nodes распределённое выполнение** — регистрация, удаление, broadcast и выполнение на удалённых нодах
- **Voice I/O** — wake-word ("Raven", "Hey Raven"), STT (Whisper/Google/Azure/Vosk), TTS (ElevenLabs/gTTS/system/Edge)
- **Выполняет задачи** — строит план из шагов, выполняет каждый инструментом, возвращает результат
- **Следит за мониторами** — пингует сайты, проверяет цены, RSS, файлы, процессы и шлёт алерты
- **Рутины по расписанию** — утренние бриффинги, проверка почты, сортировка файлов
- **RAG-память** — семантический поиск по документам, PDF/code чанкинг, память разговоров
- **Веб-дашборд** — React 19 + Monaco IDE + Tailwind
- **Multi-user + RBAC** — администраторы, пользователи, вьюеры с разграничением доступа
- **Политики безопасности** — 5 sandbox-профилей (main, non-main, code-exec, web-browsing, read-only), allow/deny инструментов для каждой сессии

---

## Быстрый старт

```bash
pip install raven-agent
# Или для разработки: pip install -e .
cp .env.example .env
# Отредактируйте .env — добавьте хотя бы один API-ключ LLM
raven onboard   # Интерактивный мастер настройки (LLM, Telegram, каналы)
raven start     # Запуск всей платформы

# Или используйте отдельные точки входа:
ravencode tui   # RavenCode — интерактивный coding-агент
ravenflow       # RavenFlow — персистентный workflow gateway
```

### Порты

| Порт | Сервис | Описание |
|------|--------|----------|
| **18888** | Web UI | Веб-чат, дашборд, Monaco IDE, настройки |
| **18789** | RavenFlow Gateway | Демон multi-agent оркестратора с WebSocket-стримингом |

Откройте в браузере:
- **http://localhost:18888** — веб-чат
- **http://localhost:18888/dashboard** — дашборд
- **http://localhost:18888/ide** — Monaco-редактор с AI-панелью

### Docker

```bash
docker compose up
```

### PostgreSQL (опционально, заменяет SQLite)

Raven по умолчанию хранит данные сервисов в SQLite. Установите `DATABASE_URL`
(или передайте `postgresql://` DSN как `db_path` хранилища), чтобы использовать
PostgreSQL для всех ключевых хранилищ (задачи, мониторы, рутины, auth, сессии,
outbox, аналитика, persister).

```bash
pip install "raven-agent[postgres]"   # установит asyncpg

# Запуск локального Postgres (user/password/db = raven)
docker compose -f docker-compose.postgres.yml up -d

# В .env
DATABASE_URL=postgresql://raven:raven@localhost:5432/raven
```

Миграции выполняются автоматически при первом подключении; данные из SQLite не переносятся.

### Web Dashboard (разработка)

```bash
cd web
npm install
npm run dev    # http://localhost:5173 (прокси на :18888)
```

---

## Сравнение

| Возможность | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|-------------|----------|------------------|---------|---------|---------|
| Self-hosted | ✅ 100% | ✅ | ❌ облако | ❌ облако | ❌ облако |
| 25+ каналов | ✅ | ❌ | ❌ | ✅ только web | ❌ |
| Coding-агент с LSP | ✅ | ❌ | ❌ | ❌ | ✅ базовый |
| Multi-agent оркестрация | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| Голос + wake word | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| Мониторы и алерты | ✅ | ❌ | ❌ | ❌ | ❌ |
| Рутины по расписанию | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG (local-first) | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBAC multi-user | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5 sandbox-профилей | ✅ | ❌ | ❌ | ❌ | ❌ |
| Canvas workspace | ✅ | ❌ | ❌ | ❌ | ❌ |
| Распределённый exec | ✅ | ❌ | ❌ | ❌ | ❌ |
| Офлайн-режим | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| Веб-дашборд | ✅ React + Monaco | ❌ только CLI | ❌ | ✅ | ✅ IDE |
| Open source | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| Бесплатно | ✅ | ✅ | ✅ | ❌ $20/мес | ❌ $10/мес |

---

## Возможности

| Возможность | Описание |
|-------------|----------|
| **25+ каналов** | Telegram (голос→текст через Whisper, инлайн-кнопки), Discord (слеш-команды + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat + ещё 15 (Telegram API, Discord API, Slack RTM, WhatsApp Cloud, Matrix CS, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat, Email IMAP, SMS Twilio, Alexa, Google Home, Discord Webhook, Telegram Webhook, Custom Webhook) |
| **RavenFlow Gateway** | Персистентный workflow-демон (`ravenflow`) на порту 18789 с multi-agent роутингом, управлением сессиями, WebSocket-стримингом, dispatch по происхождению канала, sandbox-политиками |
| **RavenCode Agent** | Автономный coding-агент (`ravencode`) — интерактивный REPL, стриминг ответов, инлайн вызовы инструментов, LSP-обогащение. Команды: `/multisession`, `/plan`, `/safe`, `/fast`, `/enrich`, `/exit` |
| **LSP Авто-обогащение** | `enrich_context()` сканирует проект, определяет языки, запускает LSP-серверы (pyright, typescript-language-server, gopls, rust-analyzer), собирает символы документа |
| **Параллельные сессии** | `SessionManager` с конкурентными `ManagedSession`-задачами, abort/cleanup, singleton-паттерн |
| **Canvas Виртуальное пространство** | Рендер rich-компонентов: текст, код, таблицы, mermaid-диаграммы, ссылки, изображения, списки, алерты. Вывод в терминал или HTML-браузер |
| **Nodes Распределённое выполнение** | Регистрация/удаление удалённых нод, выполнение задач, broadcast на все зарегистрированные эндпоинты |
| **Голосовой ввод/вывод** | Wake word ("Raven", "Hey Raven", "OK Raven"), STT (Whisper, Google, Azure, Vosk), TTS (ElevenLabs, gTTS, системный SAPI, Edge), запись с микрофона |
| **Sandbox Security Policy** | 5 политик (main, non-main, code-exec, web-browsing, read-only) с allow/deny инструментов, сетевыми ограничениями, лимитами ресурсов. Меняются на лету |
| **Cron / Планировщик** | Планирование повторяющихся задач через `cron_schedule`/`cron_list`/`cron_cancel` (на базе APScheduler) |
| **Unified Launcher** | `main.py` — запускает все сервисы (Raven, RavenFlow, Web UI) с graceful shutdown |
| **Task Engine** | Многошаговый планировщик — LLM разбивает цель на шаги, выбирает инструменты, выполняет, возвращает результат |
| **Monitor Engine** | 5 типов мониторов: HTTP(S), цена актива, RSS-лента, файл/директория, процесс. Условия срабатывания, алерты, история проверок |
| **Routines** | Автоматические рутины по расписанию: send_briefing, check_email, organize_files, send_message |
| **RAG Knowledge Base** | Embedding engine (OpenAI + локальный), векторное хранилище, чанкинг документов (PDF/TXT/код), семантический retrieval |
| **Workspace Skills** | Навыки в `workspace/skills/`: криптовалюта, утренний бриффинг, веб-поиск. Авто-загрузка через SKILL.md |
| **Web Dashboard + IDE** | React 19 + Vite + Tailwind + Monaco Editor: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings, IDE (редактор + терминал + AI-панель) |
| **Auth & RBAC** | Мультипользовательская аутентификация, 4 роли (admin/user/viewer/banned), 16 пермишенов, Bearer-токены |
| **Enterprise инфраструктура** | Circuit breaker, HTTP-пул, rate limiter, retry с экспоненциальной задержкой, audit-лог (20 типов событий), Prometheus-метрики, health checks |
| **Plugin-система** | 10 плагинов — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox с capability-based контролем |
| **Safety** | DM pairing, allowlist каналов, Fernet-шифрование секретов, rate limiting, subprocess/Docker sandbox |
| **Security Policy** | ToolPolicyEvaluator, exec.security (deny/ask/full), приоритет deny > allow, workspaceOnly FS, contextVisibility, sanitize_external_content, security audit CLI |

---

## CLI

```
raven start                    Запуск шлюза
raven stop                     Остановка
raven status                   Статус системы
raven doctor                   Диагностика
raven onboard                  Мастер настройки
raven agent --message ...      Отправить сообщение агенту
raven pairing list             Запросы на привязку
raven pairing approve CODE     Подтвердить пользователя
raven models list              Доступные модели
raven plugins list             Загруженные плагины
raven history SESSION_ID       История сообщений
raven db migrate               Миграции БД
raven db backup                Бекап БД
raven task list                Список задач
raven task run <goal>          Запустить задачу
raven task show <id>           Детали задачи
raven task cancel <id>         Отменить задачу
raven monitor list             Список мониторов
raven monitor add ...          Добавить монитор
raven code                     Интерактивный REPL кодинга
raven code --project <dir>     REPL в директории проекта
raven code --plan              Режим только планирования (без записи)
raven code --safe              Безопасный режим (подтверждения на запись)
raven code --parallel          Параллельные мультисессии
raven code index <path>        Индексация кода
raven code search <query>      Поиск по коду
raven code review <file>       Ревью файла
raven routine list             Список рутин
raven routine add ...          Добавить рутину
raven security audit           Проверка безопасности
raven security audit --deep    Глубокая проверка (сеть, env, зависимости)
raven security audit --fix     Авто-исправление проблем
raven flow serve --port 18789  Запуск RavenFlow gateway
raven flow ask <message>       Отправить сообщение в запущенный gateway
raven flow sessions            Список активных Flow-сессий

ravencode tui                  Интерактивный TUI
ravencode serve                Headless HTTP-сервер
ravencode web                  Веб-интерфейс
ravencode session list         Список сохранённых сессий
ravencode auth login           Настроить API-ключ

ravenflow --port 18789         Запуск RavenFlow gateway daemon
ravenflow serve --port 18789   Запуск RavenFlow gateway daemon
```

## Chat Commands

```
/status               Состояние бота
/new                  Новый диалог
/reset                Сброс сессии
/compact              Сжать историю
/task <goal>          Выполнить задачу
/monitor list         Список мониторов
/monitor add <type> <target>  Добавить монитор
/code index [path]    Индексация кода
/code search <query>  Поиск по коду
/code review <file>   Ревью файла
/routine list         Список рутин
/routine add <action> <sched>  Добавить рутину
/help                 Все команды
/pair <code>          Привязка пользователя
```

---

## Архитектура

```mermaid
flowchart TB
    subgraph Clients["Клиенты и каналы"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["Ядро системы"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["Наблюдаемость"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["Слой данных"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM Провайдеры"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    TG --> GW
    DC --> GW
    SL --> GW
    WA --> GW
    WB --> GW
    CLI --> GW

    GW --> CB
    CB --> RL
    RL --> AUTH

    AUTH --> AGENT
    GW --> AGENT
    AGENT --> TOOLS
    AGENT --> MEM

    OLLAMA -.-> OR
    OR -.-> ANTH
    ANTH -.-> OPENAI

    GW -->|traces/metrics| OTEL

    AGENT --> SQLITE
    AGENT --> FS

    style Clients fill:#1a1a2e,stroke:#16213e
    style Core fill:#0f3460,stroke:#1a1a2e
    style Observability fill:#1a1a3e,stroke:#2a2a5e
    style Storage fill:#1a3a2e,stroke:#16213e
    style LLM fill:#3a1a1a,stroke:#2a0a0a
```

## Project Tree

```
raven/
├── raven/                      # Main Python package (shared core)
│   ├── agent/                  ReAct agent, multi-agent registry, workspace prompts
│   ├── gateway/                RavenFlow daemon, routing engine, WebSocket streaming
│   ├── core/
│   │   ├── auth/               Authentication, RBAC (4 roles, 16 permissions), API tokens
│   │   ├── security/           ToolPolicyEvaluator, SandboxPolicy, SecurityAudit, PII redaction
│   │   ├── task_engine/        Planner, executor, task storage
│   │   ├── monitor/            HTTP, price, RSS, file, process monitors + conditions
│   │   ├── rag/                Embedding engine, chunking, vector store
│   │   ├── llm.py              LLM providers (OpenAI, Anthropic, Ollama, OpenRouter) + failover
│   │   ├── config.py           Pydantic Settings + YAML config
│   │   └── admin_api.py        Admin REST API
│   ├── channels/               25+ channels, registry, message bus, CircuitBreakerChannel
│   ├── cli/                    CLI (click + rich) — raven, ravenflow
│   ├── tools/                  Canvas, Nodes, Plugin tools
│   ├── tui/                    Terminal UI (textual)
│   ├── voice/                  Wake word detection, STT, TTS modules
│   └── workspace/              Workspace manager, skills, plugin loader
├── ravencode/                  # RavenCode — autonomous coding agent (opencode analog)
│   ├── runtime/
│   │   ├── agent_core.py       ReActAgent, AgentConfig, tool orchestration
│   │   ├── lsp.py              LSP auto-enrichment (pyright, tsserver, gopls, rust-analyzer)
│   │   ├── multisession.py     Parallel multi-session manager
│   │   └── tools.py            Tool registry (read, write, edit, bash, canvas, nodes, cron, sandbox, talk)
│   ├── cli/                    ravencode CLI (tui, serve, web, session, auth, integrations)
│   ├── agents/                 Agent orchestration, planner, debugger, coder
│   ├── api/                    OpenAI-compatible API layer
│   ├── config/                 Provider config, model registry
│   ├── integrations/           GitHub Actions, GitLab CI integration
│   └── mcp/                    MCP protocol support
├── web/                        React 19 + Vite + Tailwind dashboard + Monaco IDE
├── deploy/                     Docker, k8s, systemd, Observability stack
├── scripts/                    Build scripts, EXE builder
├── aios/                       AI-OS-MVP agent framework
├── tests/                      pytest tests (unit + integration + e2e)
└── plugins/                    User plugins
```

## Tech Stack

| Слой | Технология |
|------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite (по умолчанию) + PostgreSQL (опционально) |
| **LLM** | Ollama (local) → OpenRouter → Anthropic → OpenAI (failover) |
| **Memory** | SQLite / PostgreSQL + ChromaDB + numpy vector store |
| **RAG** | Qdrant vector store, fallback in-memory, n-gram embedding |
| **Auth** | bcrypt, JWT (HS256), RBAC (4 роли, 16 пермишенов) |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI daemon (порт 18789), routing engine, WebSocket-стриминг, multi-agent dispatch |
| **RavenCode** | Интерактивный REPL, LSP авто-обогащение (pyright/tsserver/gopls/rust-analyzer), параллельные сессии, режимы plan/safe/fast, 30+ инструментов |
| **Canvas** | Рендер rich-компонентов (код, таблица, mermaid, изображение, ссылка, список, алерт), HTML + браузер |
| **Nodes** | Распределённый реестр нод, broadcast-выполнение, async HTTP dispatch |
| **Голос** | WakeWordDetector (speech_recognition), Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **Sandbox Policy** | 5 профилей политик (main/non-main/code-exec/web-browsing/read-only), runtime allow/deny |
| **Message Broker** | NATS + JetStream (опционально, для распределённого режима) |
| **Resilience** | Circuit breaker, rate limiter, retry с экспоненциальной задержкой, audit-лог (20 типов событий), Prometheus-метрики, health checks |
| **Observability** | OpenTelemetry (traces + metrics), health/ready probes |
| **Security** | Rate limiting, JWT auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy (deny/ask/full), contextVisibility, workspace isolation, security audit CLI |
| **CI/CD** | GitHub Actions — parallel lint + typecheck + test, Allure reporting, Codecov |
| **Deploy** | Docker, docker-compose, systemd |
| **Testing** | pytest (4593+ тестов, Allure reporting), Vitest (React) |

---

## RavenCode — Terminal Coding Agent

Raven AI включает `raven code` — полнофункциональный интерактивный терминальный coding-агент:

```bash
# Запуск REPL
raven code --project ./my-project

# В REPL:
raven@project> создай REST API на FastAPI
# ... стримит ответ, делает вызовы инструментов, вносит правки в файлы

# Встроенные команды:
/help          Показать доступные команды
/multisession  Запустить подзадачи параллельно
/plan          Режим только планирования (без записи)
/safe          Безопасный режим (подтверждение перед записью)
/fast          Быстрый режим (без обогащения)
/enrich        Обновить LSP-анализ
/session <id>  Переключиться на параллельную сессию
/exit          Выход
```

### RavenFlow Gateway

Multi-agent оркестратор-демон с WebSocket-стримингом:

```bash
# Запуск gateway (отдельная команда)
ravenflow --port 18789

# Или через основной CLI
raven flow serve --port 18789

# Отправить сообщение агенту
raven flow ask "суммаризуй README"

# Список активных сессий
raven flow sessions
```

### Canvas Visual Workspace

Рендер rich-визуальных компонентов прямо из агента:

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### Unified Launcher

Единый лаунчер `main.py` запускает все сервисы:
```bash
python main.py --web-port 5173 --flow-port 18789
```

---

## Контакты

<div align="center">
  <p>
    <b>Raven AI</b> — разрабатывается <a href="https://github.com/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    Есть идея или баг? → <a href="https://github.com/ssrjkk/raven/issues">Откройте issue</a>
  </p>
  <p>
    Хотите внести вклад? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>Создан для разработчиков, которым нужен личный AI 24/7</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)
<div align="center">
  <h1>Raven AI</h1>
  <p><i>Enterprise-grade AI-ассистент. 25+ каналов. RavenFlow. RavenCode. Голос. Canvas. Nodes.</i></p>

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
  [![Tests](https://img.shields.io/badge/tests-859_passing-brightgreen)]()
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

---

## Почему Raven AI?

**Raven AI** — это не просто бот. Это полноценный автоматизированный AI-ассистент уровня enterprise, работающий 24/7 на вашем сервере.

Он думает. Он планирует. Он действует.

- **Общается в 25+ каналах** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, веб-чат + 15 более
- **RavenFlow оркестратор** — multi-agent gateway демон (порт 18789) с роутингом, управлением сессиями, WebSocket
- **RavenCode агент** — интерактивный REPL кодинг-агент (raven code) с LSP авто-обогащением, параллельными сессиями, режимами plan/safe/fast
- **Canvas визуальное пространство** — рендер компонентов (код, таблицы, mermaid диаграммы, изображения, алерты) в терминале или браузере
- **Nodes распределенное выполнение** — регистрация, удаление, broadcast и выполнение на удаленных нодах
- **Голосовой ввод/вывод** — wake word ("Raven"), STT (Whisper/Google/Azure/Vosk), TTS (ElevenLabs/gTTS/system/Edge)
- **Выполняет задачи** — построит план из шагов, выполнит каждый инструментом, вернет результат
- **Следит за мониторами** — пингует сайты, проверяет цены, RSS, файлы, процессы и шлет алерты
- **Рутины по расписанию** — утренние бриффинги, проверка почты, сортировка файлов
- **RAG-память** — семантический поиск по документам, PDF/code chunking, память разговоров
- **Веб + Десктоп** — React дашборд + Monaco IDE + Tauri desktop с bundled backend
- **Multi-user + RBAC** — админы, юзеры, вьюверы с разграничением доступа
- **Политики безопасности** — 5 sandbox профилей (main, non-main, code-exec, web-browsing, read-only), allow/deny инструментов
---

## Быстрый старт

`ash
pip install raven-agent
# Или для разработки: pip install -e .
cp .env.example .env
# Отредактируйте .env — добавьте хотя бы один API-ключ LLM
raven onboard   # Интерактивный мастер настройки (LLM, Telegram, каналы)
raven start
`

Откройте в браузере:
- **http://localhost:18888** — веб-чат
- **http://localhost:18888/dashboard** — дашборд

### Docker

`ash
docker compose up
`

### Web Dashboard (разработка)

`ash
cd web
npm install
npm run dev    # http://localhost:5173 (прокси на :18888)
`

---

## Возможности

| Возможность | Описание |
|-------------|----------|
| **25+ каналов** | Telegram (голос→текст через Whisper, инлайн-кнопки), Discord (слеш-команды + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat |
| **RavenFlow Gateway** | FastAPI демон на порту 18789 с multi-agent роутингом, управлением сессиями, WebSocket стримингом |
| **RavenCode Agent** | Интерактивный REPL кодинг-агент (`raven code`) с потоковыми ответами, inline tool calls. Команды: `/multisession`, `/plan`, `/safe`, `/fast`, `/enrich`, `/exit` |
| **LSP Авто-обогащение** | `enrich_context()` сканирует проект, определяет языки, запускает LSP (pyright, tsserver, gopls, rust-analyzer), собирает символы |
| **Параллельные сессии** | SessionManager с конкурентными ManagedSession задачами, abort/cleanup |
| **Canvas Виртуальное пространство** | Рендер rich компонентов: текст, код, таблицы, mermaid диаграммы, ссылки, изображения, списки, алерты. Вывод в терминал или HTML |
| **Nodes Распределенное выполнение** | Регистрация/удаление удаленных нод, выполнение задач, broadcast на все ноды |
| **Голосовой ввод/вывод** | Wake word ("Raven", "Hey Raven"), STT (Whisper, Google, Azure, Vosk), TTS (ElevenLabs, gTTS, SAPI, Edge) |
| **Sandbox Security Policy** | 5 политик (main, non-main, code-exec, web-browsing, read-only), allow/deny, лимиты ресурсов |
| **Cron / Планировщик** | Планирование задач через `cron_schedule`/`cron_list`/`cron_cancel` (APScheduler) |
| **EXE Сборка** | `scripts/build_exe.py` — компилирует Go сервисы, web frontend, PyInstaller в `dist/raven-ai.exe` |
| **Unified Launcher** | `main.py` — запускает NATS, Go сервисы, RavenCode, RavenFlow gateway, Web UI
| **Task Engine** | Многошаговый планировщик — LLM разбивает цель на шаги, выбирает инструменты, выполняет, возвращает результат |
| **Monitor Engine** | 5 типов мониторов: HTTP(S), цена актива, RSS-лента, файл/директория, процесс. Условия срабатывания, алерты, история проверок |
| **Coding Assistant** | Индексация кода (AST-парсинг, 8 языков), семантический поиск, ревью файлов (LLM-driven), сессии разработки |
| **Routines** | Автоматические рутины по расписанию: send_briefing, check_email, organize_files, send_message |
| **RAG Knowledge Base** | Embedding engine (OpenAI + local), векторное хранилище, чанкинг документов (PDF/TXT/код), семантический retrieval |
| **Workspace Skills** | Навыки в workspace/skills/: криптовалюта, утренний бриффинг, веб-поиск. Загружаются автоматически через SKILL.md |
| **Web Dashboard** | React 19 + Vite + Tailwind: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings |
| **Auth & RBAC** | Мультипользовательская аутентификация, 4 роли (admin/user/viewer/banned), 16 пермишенов, Bearer-токены |
| **Enterprise инфраструктура** | Circuit breaker, HTTP-пул, rate limiter, retry c экспоненциальной задержкой, audit-лог (20 типов событий), Prometheus metrics, health checks |
| **Plugin система** | 10 плагинов — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox c capability-based контролем |
| **Safety** | DM pairing, allowlist по каналам, Fernet-шифрование секретов, rate limiting, subprocess/Docker sandbox |
| **Security Policy** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow priority, workspaceOnly FS, contextVisibility, sanitize_external_content, security audit CLI |

---

## CLI

`
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
raven code                     Интерактивный REPL кодинг
raven code --project <dir>     REPL в директории проекта
raven code --plan              Режим только планирования
raven code --safe              Безопасный режим (подтверждения)
raven code --parallel          Параллельные сессии
raven code index <path>        Индексация кода
raven code search <query>      Поиск по коду
raven code review <file>       Ревью файла
raven routine list             Список рутин
raven routine add ...          Добавить рутину
raven security audit           Проверка безопасности
raven security audit --deep    Глубокая проверка
raven security audit --fix     Авто-исправление проблем
raven flow serve --port 18789  Запуск RavenFlow gateway
raven flow ask <message>       Отправить сообщение gateway
raven flow sessions            Список активных сессий
`

## Chat Commands

`
/status               Состояние бота
/new                  Новый диалог
/reset                Сброс сессии
/compact              Сжать историю
/task <goal>          Выполнить задачу
/monitor list         Мониторы
/monitor add <type> <target>  Добавить монитор
/code index [path]    Индексация
/code search <query>  Поиск по коду
/code review <file>   Ревью
/routine list         Рутины
/routine add <action> <sched>  Добавить рутину
/help                 Все команды
/pair <code>         Привязка пользователя
`

---

## Архитектура

`mermaid
flowchart TB
    subgraph Clients["Клиенты и каналы"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Gateway["API Gateway"]
        GW["Gateway (Go)\n:8000"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT Validation"]
    end

    subgraph Services["Микросервисы"]
        AS["Auth Service (Go)\n:8001 — JWT, SQLite, gRPC"]
        AC["Agent Core (Python)\n:8002 — LLM Router"]
        ME["Monitor Engine (Go)\n:8003 — SQLite, NATS"]
        RS["RAG Service (Python)\n:8004 — Qdrant"]
        TE["Task Engine (Python)\n:8005 — SQLite, Outbox, Saga"]
        CS["Code Service (Python)\n:8006 — Sandbox"]
    end

    subgraph Observability["Observability"]
        OTEL["OTel Collector\n:4317 gRPC / :4318 HTTP"]
        TEMPO["Tempo\nTrace Storage"]
        LOKI["Loki\nLog Aggregation"]
        PROM["Prometheus\n:9090"]
        GRAF["Grafana\n:3000 — Dashboards"]
    end

    subgraph Messaging["Message Broker"]
        NATS["NATS / JetStream\n:4222"]
    end

    subgraph Storage["Data Layer"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store :6333"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM Провайдеры"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    subgraph AgentSystem["Agent System"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
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
    AUTH --> AS
    GW --> AC
    GW --> ME
    GW --> RS
    GW --> TE
    GW --> CS
    AC --> LLM
    AC --> AGENT
    AGENT --> TOOLS
    AGENT --> MEM
    OLLAMA -.-> OR
    OR -.-> ANTH
    ANTH -.-> OPENAI
    AC -.->|agent.response| NATS
    ME -.->|monitor.check.completed| NATS
    TE -.->|task.events| NATS
    AS -.->|auth.user.created| NATS
    GW -->|traces/metrics| OTEL
    AS -->|traces/metrics| OTEL
    AC -->|traces/metrics| OTEL
    ME -->|traces/metrics| OTEL
    RS -->|traces/metrics| OTEL
    TE -->|traces/metrics| OTEL
    CS -->|traces/metrics| OTEL
    WB -->|traces| OTEL
    OTEL --> TEMPO
    OTEL --> LOKI
    PROM --> GW
    PROM --> AS
    PROM --> ME
    PROM --> OTEL
    GRAF --> PROM
    GRAF --> TEMPO
    GRAF --> LOKI
    AS --> SQLITE
    ME --> SQLITE
    TE --> SQLITE
    RS --> QDRANT
    CS --> FS
    AGENT --> FS

    style Clients fill:#1a1a2e,stroke:#16213e
    style Gateway fill:#0f3460,stroke:#1a1a2e
    style Services fill:#16213e,stroke:#0f3460
    style Observability fill:#1a1a3e,stroke:#2a2a5e
    style Messaging fill:#2d1b69,stroke:#1a1a2e
    style Storage fill:#1a3a2e,stroke:#16213e
    style LLM fill:#3a1a1a,stroke:#2a0a0a
    style AgentSystem fill:#1a2a3a,stroke:#0f3460
`

## Project Tree

```
raven/
├── raven/                      # Main Python package
│   ├── agent/                  ReAct agent, multi-agent registry, workspace prompts
│   ├── gateway/                Message routing, RavenFlow daemon, routing engine
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
│   ├── cli/                    CLI (click + rich) — raven code, raven flow
│   ├── tools/                  Canvas, Nodes, Plugin tools
│   ├── tui/                    Terminal UI (textual)
│   ├── voice/                  Wake word detection, STT, TTS modules
│   └── workspace/              Workspace manager, skills, plugin loader
├── ravencode/                  # RavenCode agent framework
│   ├── runtime/
│   │   ├── lsp.py              LSP auto-enrichment (pyright, tsserver, gopls, rust-analyzer)
│   │   ├── multisession.py     Parallel multi-session manager
│   │   └── tools.py            Tool registry (read, write, edit, bash, canvas, nodes, cron, sandbox, talk)
│   └── cli/coding.py           Interactive REPL coding agent
├── services/                   # Microservices (Go + Python)
│   ├── gateway/                Go gateway (auth proxy, circuit breaker, rate limiter, metrics, gRPC)
│   ├── auth/                   Go auth service (SQLite, JWT, gRPC, Redis rate limiter)
│   ├── agent-core/             Python — LLM router (Ollama/OpenAI/Anthropic), NATS pub/sub
│   ├── monitor-engine/         Go monitor service (SQLite, NATS, Prometheus)
│   ├── rag-service/            Python — semantic search (Qdrant + in-memory fallback)
│   ├── task-engine/            Python — task planner (SQLite, NATS, idempotency, outbox, saga)
│   ├── code-service/           Python — code sandbox + RavenCode agent API + AST context
│   └── proto/                  Protobuf definitions + generated Go code
├── web/                        React 19 + Vite + Tailwind dashboard + Monaco IDE
├── desktop-tauri/              Tauri desktop shell (Rust) with backend launcher
├── deploy/                     Docker, k8s, systemd, Observability stack
├── daemon/                     Rust daemon (ravend): system metrics, process management
├── scripts/                    Build scripts, EXE builder
├── aios/                       AI-OS-MVP agent framework
└── plugins/                    User plugins
```

## Технологии

| Слой | Технология |
|------|-----------|
| **Backend** | Python 3.13+, FastAPI, asyncio, SQLite (modernc.org/sqlite) |
| **LLM** | Ollama (local) → OpenRouter → Anthropic → OpenAI (failover) |
| **Memory** | SQLite + ChromaDB + numpy vector store |
| **RAG** | Qdrant vector store, fallback in-memory, n-gram embedding |
| **Auth** | bcrypt, JWT (HS256), gRPC, RBAC (4 роли, 16 пермишенов) |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI демон (порт 18789), routing engine, WebSocket стриминг, multi-agent dispatch |
| **RavenCode** | Интерактивный REPL, LSP авто-обогащение (pyright/tsserver/gopls/rust-analyzer), параллельные сессии, 30+ инструментов |
| **Canvas** | Рендер компонентов (код, таблица, mermaid, изображение, ссылка, список, алерт), HTML + браузер |
| **Nodes** | Распределенный реестр нод, broadcast выполнение, async HTTP dispatch |
| **Голос** | WakeWordDetector, Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **Sandbox Policy** | 5 профилей политик (main/non-main/code-exec/web-browsing/read-only), runtime allow/deny |
| **Message Broker** | NATS + JetStream (streams: agent.response, monitor.check.completed, task.events, auth.user.created) |
| **Gateway** | Go 1.26 — circuit breaker, rate limiter, auth proxy, gRPC retry, OpenTelemetry |
| **Auth Service** | Go 1.26 — SQLite, JWT, gRPC, token bucket rate limiter, OpenTelemetry |
| **Monitor Engine** | Go 1.26 — HTTP health checks, SQLite, NATS events, Prometheus metrics |
| **Resilience** | Circuit breaker, gRPC retry (exponential backoff), rate limiter, outbox pattern, saga pattern, idempotency |
| **Observability** | OpenTelemetry (traces + metrics), Prometheus, Grafana (12 панелей), Loki, Tempo, health/ready probes |
| **Security** | Rate limiting, JWT auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy (deny/ask/full), contextVisibility, workspace isolation, security audit CLI |
| **CI/CD** | GitHub Actions — parallel Go/Python/web lint + test + build, Allure TestOps, Docker buildx, Codecov, Playwright E2E, k6 load tests |
| **Deploy** | Docker (multi-stage, distroless, non-root), docker-compose (microservice stack), Kubernetes manifests, systemd, launchd |
| **Testing** | pytest (800+ тестов, Allure reporting), Go table-driven tests, Vitest (React), Playwright (E2E), k6 (load) |

---

## RavenCode — Terminal Coding Agent

Raven AI includes `raven code`, a full-featured interactive terminal coding agent:

```bash
# Start the REPL
raven code --project ./my-project

# In the REPL:
raven@project> create a REST API with FastAPI
# ... streams response, makes tool calls, edits files inline

# Built-in commands:
/help          Show available commands
/multisession  Run subtasks in parallel
/plan          Toggle plan-only mode (no writes)
/safe          Toggle safe mode (confirm before writes)
/fast          Toggle fast mode (skip enrichment)
/enrich        Refresh LSP analysis
/session <id>  Switch to a parallel session
/exit          Exit
```

### RavenFlow Gateway

Multi-agent orchestrator daemon with WebSocket streaming:

```bash
# Start the gateway
raven flow serve --port 18789

# Send an agent message
raven flow ask "summarize the README"

# List active sessions
raven flow sessions
```

### Canvas Visual Workspace

Render rich visual components directly from the agent:

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### Unified Desktop App

A single `main.py` launcher runs all services:
```bash
python main.py --web-port 5173 --flow-port 18789
```

Build everything into one EXE:
```bash
python scripts/build_exe.py
# Output: dist/raven-ai.exe
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
  <p><i>Enterprise-grade AI-ассистент. 25+ каналов. RavenFlow. RavenCode. Голос. Canvas. Nodes.</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

<div align="center">
  <h1>Raven AI</h1>
  <p><i>Персональный ИИ-помощник корпоративного уровня. 12 каналов. Механизм задач. Мониторы. Помощник по программированию. База знаний RAG. Веб-панель управления.</i></p>

  <a href="#features">Features</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#license">License</a>


  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/channels-12-8A2BE2" alt="Channels">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/tests-616_passing-brightgreen" alt="Tests">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/security-hardened-blueviolet" alt="Security">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/aios-mvp-purple" alt="AI-OS-MVP">
  </a>
  <a href="https://github.com/ssrjkk/raven">
    <img src="https://img.shields.io/badge/hybrid-web+api+desktop-orange" alt="Hybrid Architecture">
  </a>
</div>

<img width="1254" height="1254" alt="image" src="https://github.com/user-attachments/assets/d7e95b8a-72c7-43e1-b67b-310fc35f1f66" />


---

## Why Raven AI?

**Raven AI** — это не просто бот. Это полноценный автоматизированный AI-ассистент уровня enterprise, работающий 24/7 на вашем сервере.

Он думает. Он планирует. Он действует.

- **Общается в 12 мессенджерах** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE + веб-чат
- **Выполняет задачи** — построит план из шагов, выполнит каждый инструментом, вернет результат
- **Следит за мониторами** — пингует сайты, проверяет цены, RSS, файлы, процессы и шлет алерты
- **Пишет код** — индексирует кодобазу, ищет символы, ревьюит файлы, ведет сессии разработки
- **Рутины по расписанию** — утренние бриффинги, проверка почты, сортировка файлов
- **RAG-память** — семантический поиск по документам, chunking PDF/кода, memory conversations
- **Веб-дашборд** — React-панель с мониторингом, управлением задачами, мониторами и рутинами
- **Multi-user + RBAC** — админы, юзеры, вьюверы с разграничением доступа

---

## Quickstart

```bash
pip install raven-agent
# Или для разработки: pip install -e .
cp .env.example .env
# Отредактируйте .env — добавьте хотя бы один API-ключ LLM
raven onboard   # Интерактивный мастер настройки (LLM, Telegram, каналы)
raven start
```

Откройте в браузере:
- **http://localhost:18888** — веб-чат
- **http://localhost:18888/dashboard** — дашборд

### Docker

```bash
docker compose up
```

### Web Dashboard (разработка)

```bash
cd web
npm install
npm run dev    # http://localhost:5173 (прокси на :18888)
```

---

## Features

| Возможность | Описание |
|-------------|----------|
| **12 каналов** | Telegram (голос→текст через Whisper, инлайн-кнопки), Discord (слеш-команды + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat |
| **Task Engine** | Многошаговый планировщик — LLM разбивает цель на шаги, выбирает инструменты, выполняет, возвращает результат |
| **Monitor Engine** | 5 типов мониторов: HTTP(S), цена актива, RSS-лента, файл/директория, процесс. Условия срабатывания, алерты, история проверок |
| **Coding Assistant** | Индексация кода (AST-парсинг, 8 языков), семантический поиск, ревью файлов (LLM-driven), сессии разработки |
| **Routines** | Автоматические рутины по расписанию: send_briefing, check_email, organize_files, send_message |
| **RAG Knowledge Base** | Embedding engine (OpenAI + local), векторное хранилище, чанкинг документов (PDF/TXT/код), семантический retrieval |
| **Workspace Skills** | Навыки в `workspace/skills/`: криптовалюта, утренний бриффинг, веб-поиск. Загружаются автоматически через SKILL.md |
| **Web Dashboard** | React 19 + Vite + Tailwind: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings |
| **Auth & RBAC** | Мультипользовательская аутентификация, 4 роли (admin/user/viewer/banned), 16 пермишенов, Bearer-токены |
| **Enterprise инфраструктура** | Circuit breaker, HTTP-пул, rate limiter, retry c экспоненциальной задержкой, audit-лог (20 типов событий), Prometheus metrics, health checks |
| **Plugin система** | 10 плагинов — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox c capability-based контролем |
| **Safety** | DM pairing, allowlist по каналам, Fernet-шифрование секретов, rate limiting, subprocess/Docker sandbox |
| **Security Policy** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow priority, workspaceOnly FS, contextVisibility, sanitize_external_content, security audit CLI |

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
raven code index <path>        Индексация кода
raven code search <query>      Поиск по коду
raven code review <file>       Ревью файла
raven routine list             Список рутин
raven routine add ...          Добавить рутину
raven security audit           Проверка безопасности
raven security audit --deep    Глубокая проверка (сеть, env, зависимости)
raven security audit --fix     Авто-исправление проблем
```

## Chat Commands

```
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
```

---

## Architecture

```
raven-ai/
├── core/
│   ├── agent/          ReAct-агент, multi-agent registry, workspace prompts
│   ├── gateway/        Маршрутизация сообщений, сессии, команды
│   ├── auth/           Аутентификация, RBAC (4 роли, 16 пермишенов), API-токены
│   ├── rag/            Векторное хранилище, embeddings, чанкинг, retriever
│   ├── task_engine/    Планировщик, исполнитель, хранилище задач
│   ├── monitor/        HTTP, price, RSS, file, process мониторы + условия
│   ├── security/       ToolPolicyEvaluator, ContextVisibility, sanitize_external_content, SecurityAudit
│   ├── coder/          Индексатор, парсер AST, ревьюер, менеджер сессий
│   ├── routine/        Движок рутин, хранилище (бриффинги, email, файлы)
│   ├── admin_api.py    REST API (каналы, агенты, конфиг, секреты, задачи, аудит)
│   ├── audit.py        Структурированный JSON audit-лог (20 типов событий)
│   ├── circuit_breaker.py  Closed → Open → Half-Open с метриками
│   ├── errors.py       20 типизированных ErrorCode + авто-классификация
│   ├── llm.py          Маршрутизация: OpenRouter, Anthropic, OpenAI, Ollama
│   ├── failover.py     Weighted-взвешенный failover с circuit breaker
│   ├── sandbox.py      Изоляция: direct, subprocess, Docker
│   ├── plugins/        Система плагинов с capability-based sandbox
│   └── middleware.py   Rate limit, auth, request ID, error handler
├── channels/           12 enterprise-каналов
├── web/                React 19 + Vite + Tailwind дашборд
├── plugins/            10 плагинов (browser, code, cron, files, git...)
├── tools/              file, shell, notify, browser
├── routines/           briefing, email, file organizer
├── monitors/           http, price, rss, file, process
├── workspace/
│   └── skills/         crypto, briefing, web_search (SKILL.md)
└── .github/            GitHub Actions CI (pytest + ruff, 3.11-3.13)
```

---

## Tech Stack

| Слой | Технология |
|------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite |
| **LLM** | OpenRouter / Anthropic / OpenAI / Ollama |
| **Memory** | SQLite + ChromaDB + numpy vector store |
| **RAG** | OpenAI embeddings / sentence-transformers, cosine similarity |
| **Auth** | PBKDF2, Bearer tokens, RBAC |
| **Frontend** | React 19, Vite, Tailwind CSS 4, react-router-dom |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, Graph API |
| **Monitor Engine** | 5 типов (HTTP, price, RSS, file, process), ConditionEvaluator, AlertDispatcher |
| **Routine Engine** | Интервальные и scheduled рутины с `_parse_cron`, логированием |
| **Workspace Skills** | SKILL.md в `workspace/skills/`, авто-загрузка через SkillsRegistry |
| **Observability** | Prometheus metrics, JSON audit, health checks, correlation IDs |
| **Security** | Rate limiting, API auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy, contextVisibility, workspace isolation, security audit CLI |
| **Resilience** | Circuit breaker, retry, connection pooling, hot-reload |
| **CI** | GitHub Actions (pytest, ruff lint, compile check) |
| **Deploy** | Docker, docker-compose |

---

## AI-OS-MVP — Hybrid Architecture

Raven AI теперь работает в гибридной архитектуре **AI-OS-MVP**:

```
raven-ai/
├── aios/                       # AI-OS-MVP bridge (Python)
│   ├── api/bridge.py           # AI Gateway endpoint
│   ├── agents/orchestrator.py  # Agent orchestrator
│   └── runtime/adapter.py      # Unified runtime
├── web/                        # Web IDE (React 19)
│   └── src/pages/IDE.tsx       # IDE with editor + terminal
├── desktop/                    # Electron desktop
├── desktop-tauri/              # Tauri desktop (Rust)
├── packages/                   # TypeScript packages
│   ├── ai-core/                # AI роутер + провайдеры
│   ├── agents/                 # multi-agent система
│   ├── runtime/                # terminal, fs, docker
│   └── repo/                   # индексер, AST, embeddings
```

### Быстрый старт AI-OS-MVP

```bash
# AI Gateway (bridge над Raven)
raven aios gateway --port 3001

# Запустить автономного агента
raven aios run "создай REST API" --agent autonomous

# Выполнить команду
raven aios exec "npm run dev"

# Web IDE (Monaco редактор)
cd web && npm install && npm run dev
# Открой http://localhost:5173/ide
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
  <p><i>Built for developers who need their personal AI 24/7</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

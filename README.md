<div align="center">
  <h1> Raven AI</h1>
  <p><i>Enterprise-grade personal AI assistant. 12 channels. Zero compromise.</i></p>
</div>

---

## Features

| Feature | Description |
|---------|-------------|
| Language | Python 3.11+ |
| Architecture | asyncio monorepo with circuit breakers, retry, rate limit |
| Channels | 12: Telegram, Discord, WebChat, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE |
| Memory | Built-in (SQLite + vector recall) |
| Stateless mode | `raven start --stateless` |
| Web UI | Built-in FastAPI + WebSocket |
| LLM Providers | OpenRouter, Anthropic, OpenAI, Ollama |
| Model Failover | Weighted fallback across providers with circuit breaker |
| Plugin System | 10 plugins: api, browser, code, cron, files, git, memory, ocr, process, sessions |
| Plugin Sandbox | Capability-based access control (network, shell, browser...) |
| Sandboxing | Direct, subprocess, and Docker execution modes |
| Skills/Playbooks | SKILL.md registry with workspace loading |
| Webhooks | Generic, Slack events, WhatsApp, Google Chat, Signal, Teams, Feishu, LINE |
| Chat Commands | /status, /new, /reset, /compact, /think, /verbose, /trace, /usage, /restart, /activation, /help, /skills, /pair |
| Multi-Agent | Per-channel routing with isolated agent configs |
| Workspace | AGENTS.md, SOUL.md, TOOLS.md prompt injection |
| Security | DM pairing, per-channel allowlist, rate limiting, API auth, Fernet secrets encryption |
| Observability | Structured JSON audit log, Prometheus metrics, health checks |
| Admin API | RESTful management: channels, agents, sessions, config, secrets, jobs, audit |
| Background Jobs | Async job manager with status tracking and cancellation |
| Config Hot-Reload | Auto-detect .env changes without restart |
| CI/CD | GitHub Actions (lint + test, Python 3.11-3.13) |
| Deployment | Docker, docker-compose |

## Quickstart

```bash
pip install -e .
cp .env.example .env
# Edit .env with your API keys
raven start
```

Open **http://localhost:18888** for the web UI.

### Docker

```bash
docker compose up
```

## Enterprise Infrastructure

| Module | What it does |
|--------|-------------|
| `core/errors.py` | `AppError` with 20 typed `ErrorCode`s, `classify_error()` auto-classification |
| `core/circuit_breaker.py` | Closed → Open → Half-Open state machine with configurable threshold, recovery timeout, metrics |
| `core/http_client.py` | Shared `httpx.AsyncClient` pool with connection limits, keepalive, User-Agent |
| `core/jobs.py` | Async `JobManager` — submit, cancel, list, status tracking, duration metrics |
| `core/secrets.py` | `SecretsManager` — Fernet/PBKDF2 encryption of sensitive config values with file persistence |
| `core/config_watcher.py` | `ConfigWatcher` — polls .env for changes, hot-reloads into `os.environ`, listener callbacks |
| `core/audit.py` | `AuditLogger` — structured JSON event log (20 event types), `sensitive()` marker, `recent()` query |
| `core/plugin_sandbox.py` | `PluginSandbox` — capability-based `check()` with global deny + per-plugin allow lists |
| `core/admin_api.py` | RESTful admin API at `/api/admin/*` — health, channels, agents, sessions, audit, config, secrets, jobs |
| `channels/enterprise_base.py` | `EnterpriseChannel` — `RateLimiter`, `_retry_call()`, `_post()` via shared HTTP pool, `stats()`, `health_check()` |

## Channels

| Channel | Status | Integration |
|---------|--------|-------------|
| WebChat | ✅ Built-in | FastAPI + WebSocket |
| Telegram | ✅ Built-in | python-telegram-bot |
| Discord | ✅ Built-in | discord.py |
| Slack | ✅ Enterprise | slack-sdk async |
| WhatsApp | ✅ Enterprise | Graph API + Webhook |
| Matrix | ✅ Enterprise | Matrix Client-Server API + sync loop |
| Google Chat | ✅ Enterprise | Google Chat API + Webhook |
| Signal | ✅ Enterprise | signal-cli REST API |
| IRC | ✅ Enterprise | asyncio raw sockets + auto-reconnect |
| Microsoft Teams | ✅ Enterprise | Teams Webhook + API |
| Feishu/Lark | ✅ Enterprise | Feishu Open API + auto-refresh token |
| LINE | ✅ Enterprise | LINE Messaging API |

All channels include: rate limiting, retry with exponential backoff, structured audit, Prometheus metrics, health checks, connection pooling.

## Admin REST API

| Endpoint | Description |
|----------|-------------|
| `GET /api/admin/health` | Full health check |
| `GET /api/admin/health/ready` | Readiness probe |
| `GET /api/admin/metrics` | Metrics snapshot |
| `GET /api/admin/metrics/prometheus` | Prometheus format |
| `GET /api/admin/channels` | List channels with stats |
| `GET /api/admin/channels/{id}` | Channel details |
| `POST /api/admin/channels/{id}/restart` | Restart channel |
| `GET /api/admin/agents` | List agents |
| `GET /api/admin/sessions` | List sessions |
| `GET /api/admin/audit` | Recent audit events |
| `GET /api/admin/config` | Current config |
| `GET /api/admin/secrets` | List secret keys |
| `POST /api/admin/secrets/{key}` | Set encrypted secret |
| `DELETE /api/admin/secrets/{key}` | Delete secret |
| `GET /api/admin/jobs` | List background jobs |
| `DELETE /api/admin/jobs/{id}` | Cancel a job |
| `POST /api/admin/shutdown` | Graceful shutdown |
| `GET /api/admin/system/status` | System overview |

## CLI

```
raven start                    Launch the gateway
raven stop                     Stop daemon
raven status                   System status
raven doctor                   Diagnostics
raven onboard                  Setup wizard
raven agent --message ...      Send message to agent
raven pairing list             Pending pairings
raven pairing approve CODE     Approve user
raven models list              Available models
raven plugins list             Loaded plugins
raven history SESSION_ID       View messages
raven nodes list               List device nodes
raven nodes pair DEVICE_ID     Pair a device
raven db migrate               Run migrations
raven db backup                Backup database
```

## Chat Commands

```
/status               Show bot status
/new                  Start fresh conversation
/reset                Reset current session
/compact              Summarize and compress session
/think <level>        Set thinking effort (low|medium|high)
/verbose <on|off>     Toggle verbose output
/trace <on|off>       Toggle trace mode
/usage <off|tokens|full>  Set usage display
/restart              Restart agent session
/activation <mode>    Set activation mode (mention|always)
/help                 Show all commands
/skills               List loaded skills
/pair <code>          Authorize with pairing code
```

## Plugins

| Plugin | Description |
|--------|-------------|
| **sessions** | List, history, send, spawn sessions |
| **memory** | Vector store — remember, recall, search |
| **browser** | Playwright web browsing, screenshots, search |
| **cron** | APScheduler cron-based task scheduling |
| **code** | Sandboxed Python execution, review, explain |
| **files** | File reading and manipulation |
| **api** | HTTP requests (GET, POST, PUT, DELETE) |
| **ocr** | Tesseract OCR — text extraction from images |
| **process** | System process management (run, list, kill) |
| **git** | Git operations (status, log, diff, commit, push, pull) |

## Security

- **DM Policy**: `pairing` (default), `open`, or `closed`
- **Pairing**: Users send `/pair CODE` to authorize via `raven pairing approve`
- **Allowlist**: Per-channel via `CHANNEL_ALLOW_FROM='{"discord":["*"]}'`
- **Plugin Sandbox**: Capability-based restrictions (network, shell, browser, filesystem...)
- **Secrets Encryption**: Fernet/PBKDF2 encryption for sensitive config values
- **Sandbox**: Subprocess isolation (no network, temp dir, timeout) or full Docker sandbox
- **Rate Limiting**: Configurable per-minute throttle (global + per-channel)
- **API Auth**: X-Raven-Key header required on all sensitive endpoints
- **Audit Log**: Every message, auth event, and admin action is logged

## Environment

### LLM & Core

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OLLAMA_BASE_URL` | — | Ollama server URL |
| `DEFAULT_MODEL` | `openrouter/openai/gpt-4o` | Default LLM model |
| `RAVEN_MASTER_KEY` | — | Master key for secrets encryption |

### Channels

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `DISCORD_BOT_TOKEN` | — | Discord bot token |
| `SLACK_BOT_TOKEN` | — | Slack bot token |
| `SLACK_SIGNING_SECRET` | — | Slack signing secret |
| `MATRIX_HOMESERVER` | `https://matrix.org` | Matrix homeserver URL |
| `MATRIX_ACCESS_TOKEN` | — | Matrix access token |
| `WHATSAPP_TOKEN` | — | WhatsApp Graph API token |
| `WHATSAPP_PHONE_ID` | — | WhatsApp phone number ID |
| `GOOGLECHAT_WEBHOOK_URL` | — | Google Chat incoming webhook |
| `SIGNAL_API_URL` | `http://localhost:8080` | signal-cli REST API URL |
| `IRC_SERVER` | `irc.libera.chat` | IRC server address |
| `IRC_PORT` | `6697` | IRC server port |
| `IRC_NICK` | `raven-bot` | IRC nickname |
| `IRC_PASSWORD` | — | NickServ password |
| `IRC_CHANNELS` | `#raven` | Comma-separated channels to join |
| `TEAMS_WEBHOOK_URL` | — | Teams incoming webhook |
| `FEISHU_WEBHOOK_URL` | — | Feishu webhook URL |
| `FEISHU_APP_ID` | — | Feishu app ID |
| `FEISHU_APP_SECRET` | — | Feishu app secret |
| `LINE_CHANNEL_TOKEN` | — | LINE channel access token |
| `LINE_CHANNEL_SECRET` | — | LINE channel secret |

### Security & Operations

| Variable | Default | Description |
|----------|---------|-------------|
| `DM_POLICY` | `pairing` | Access policy |
| `WEB_PORT` | `18888` | Web UI port |
| `WEB_SECRET_KEY` | — | API auth key |
| `WEB_CORS_ORIGINS` | `*` | CORS allowed origins |
| `CHANNEL_ALLOW_FROM` | — | Per-channel allowlist JSON |
| `RATE_LIMIT_MAX` | `60` | Requests per window |
| `RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |

### Storage & LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `data/raven.db` | SQLite path |
| `LOG_FILE` | `data/raven.log` | Log file path |
| `LOG_LEVEL` | `INFO` | Log level |
| `JSON_LOG` | `true` | Structured JSON logging |
| `WORKSPACE_PATH` | — | Agent workspace (AGENTS.md/SOUL.md/TOOLS.md) |
| `LLM_TIMEOUT` | `120` | LLM request timeout |
| `LLM_RETRY_MAX` | `3` | LLM retry attempts |
| `LLM_RETRY_DELAY` | `1.0` | LLM retry base delay |

## Architecture

```
raven-ai/
├── core/
│   ├── agent/          ReAct agent, multi-agent registry, workspace prompts
│   ├── gateway/        Message routing, session management, chat commands
│   ├── admin_api.py    RESTful admin API (channels, agents, config, secrets, jobs, audit)
│   ├── audit.py        Structured JSON event log (20 event types)
│   ├── circuit_breaker.py  Stateful circuit breaker (closed/open/half-open)
│   ├── errors.py       Typed error framework (20 ErrorCodes, classify_error)
│   ├── http_client.py  Shared httpx connection pool (limits, keepalive)
│   ├── jobs.py         Async background job manager
│   ├── secrets.py      Fernet/PBKDF2 secrets encryption
│   ├── config_watcher.py  Hot-reload .env on change
│   ├── plugin_sandbox.py  Capability-based plugin access control
│   ├── config.py       Pydantic settings (all env vars)
│   ├── db.py           SQLite with migrations
│   ├── llm.py          LLM router (OpenRouter, Anthropic, OpenAI, Ollama)
│   ├── failover.py     Weighted model failover
│   ├── sandbox.py      Execution sandbox (direct, subprocess, Docker)
│   ├── skills.py       Skill registry with SKILL.md loading
│   ├── health.py       Health check registry
│   ├── metrics.py      Prometheus metrics collector
│   ├── logging.py      JSON logging, correlation IDs
│   ├── middleware.py   Request ID, rate limit, auth, error handler
│   └── webhooks.py     Generic, Slack, WhatsApp, Google Chat, Signal, Teams, Feishu, LINE
├── channels/
│   ├── enterprise_base.py  Base class: RateLimiter, retry, audit, metrics, HTTP pool
│   ├── telegram/       python-telegram-bot adapter
│   ├── discord/        discord.py adapter
│   ├── webchat/        FastAPI + WebSocket adapter
│   ├── slack/          slack-sdk async adapter
│   ├── whatsapp/       Graph API + webhook
│   ├── matrix/         Matrix Client-Server API + sync loop
│   ├── googlechat/     Google Chat API + webhook
│   ├── signal/         signal-cli REST API
│   ├── irc/            asyncio raw sockets + auto-reconnect
│   ├── teams/          Teams webhook + API
│   ├── feishu/         Feishu Open API + auto-refresh token
│   └── line/           LINE Messaging API
├── plugins/            10 plugins (api, browser, code, cron, files, git, memory, ocr, process, sessions)
├── cli/                CLI with 15+ commands
├── .github/            GitHub Actions CI (3.11-3.13)
├── data/               SQLite DB, audit log, encrypted secrets
└── workspace/          AGENTS.md, SOUL.md, TOOLS.md, skills/
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite |
| **LLM** | OpenRouter, Anthropic, OpenAI, Ollama |
| **Memory** | SQLite (relational + vector recall) |
| **Observability** | Prometheus metrics, structured JSON audit, health checks, correlation IDs |
| **Security** | Rate limiting, API auth, DM pairing, per-channel allowlist, Fernet encryption, plugin sandbox |
| **Resilience** | Circuit breakers, exponential backoff retry, connection pooling, config hot-reload |
| **CI** | GitHub Actions (pytest, ruff lint, import check) |
| **Deploy** | Docker, docker-compose |

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

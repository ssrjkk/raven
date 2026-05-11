<div align="center">
  <h1>🐦 Raven AI</h1>
  <p><i>Your personal AI assistant. Any channel. Always on.</i></p>
</div>

---

## Features

| Feature | Description |
|---------|-------------|
| Language | Python 3.11+ |
| Architecture | asyncio monorepo |
| Channels | 12: Telegram, Discord, WebChat, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE |
| Memory | Built-in (SQLite + vector recall) |
| Stateless mode | `raven start --stateless` |
| Web UI | Built-in FastAPI + WebSocket |
| LLM Providers | OpenRouter, Anthropic, OpenAI, Ollama |
| Model Failover | Weighted fallback across providers |
| Plugin System | 10 plugins: api, browser, code, cron, files, git, memory, ocr, process, sessions |
| Sandboxing | Direct, subprocess, and Docker execution modes |
| Skills/Playbooks | SKILL.md registry with workspace loading |
| Webhooks | Generic, Slack events, WhatsApp verification endpoints |
| Chat Commands | /status, /new, /reset, /compact, /think, /verbose, /trace, /usage, /restart, /activation, /help, /skills, /pair |
| Multi-Agent | Per-channel routing with isolated agent configs |
| Workspace | AGENTS.md, SOUL.md, TOOLS.md prompt injection |
| Security | DM pairing, per-channel allowlist, rate limiting, API auth |
| Observability | Structured JSON logging, Prometheus metrics, health checks |
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

## Channels

| Channel | Status |
|---------|--------|
| WebChat | ✅ Built-in |
| Telegram | ✅ Built-in |
| Discord | ✅ Built-in |
| Slack | 📦 slack-sdk |
| WhatsApp | 📦 Webhook |
| Matrix | 📦 httpx |
| Google Chat | 📦 Webhook |
| Signal | 📦 signal-cli |
| IRC | 📦 irclib |
| Microsoft Teams | 📦 Webhook |
| Feishu/Lark | 📦 Webhook |
| LINE | 📦 Webhook |

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
- **Sandbox**: Subprocess isolation (no network, temp dir, timeout) or full Docker sandbox
- **Rate Limiting**: Configurable per-minute throttle
- **API Auth**: X-Raven-Key header required on all API endpoints

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `OLLAMA_BASE_URL` | — | Ollama server URL |
| `DEFAULT_MODEL` | `openrouter/openai/gpt-4o` | Default LLM model |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `DISCORD_BOT_TOKEN` | — | Discord bot token |
| `SLACK_BOT_TOKEN` | — | Slack bot token |
| `DM_POLICY` | `pairing` | Access policy |
| `WEB_PORT` | `18888` | Web UI port |
| `WEB_SECRET_KEY` | — | API auth key |
| `DB_PATH` | `data/raven.db` | SQLite path |
| `WORKSPACE_PATH` | — | Agent workspace (AGENTS.md/SOUL.md/TOOLS.md) |
| `CHANNEL_ALLOW_FROM` | — | Per-channel allowlist JSON |
| `JSON_LOG` | `true` | Structured JSON logging |
| `RATE_LIMIT_MAX` | `60` | Requests per window |

## Architecture

```
raven-ai/
├── core/              Event bus, agent loop, LLM router, failover
│   ├── agent/         ReAct agent, multi-agent registry, workspace prompts
│   ├── gateway/       Message routing, session management, chat commands
│   ├── logging/       Structured JSON logging, audit, correlation IDs
│   ├── health/        Health check registry (DB, LLM)
│   ├── metrics/       Prometheus metrics collector
│   ├── middleware/     Rate limiter, auth, request ID
│   ├── sandbox/       Execution sandbox (direct, subprocess, Docker)
│   ├── skills/        Skill registry with SKILL.md loading
│   └── webhooks/      Generic, Slack, WhatsApp webhook endpoints
├── channels/          12 messaging adapters
├── plugins/           10 plugins
├── cli/               CLI with 15+ commands
├── .github/           GitHub Actions CI
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite |
| **LLM** | OpenRouter, Anthropic, OpenAI, Ollama |
| **Memory** | SQLite (relational + vector recall) |
| **Observability** | Prometheus metrics, structured JSON logging, health checks |
| **Security** | Rate limiting, API auth, DM pairing, per-channel allowlist |
| **CI** | GitHub Actions (pytest, ruff lint) |
| **Deploy** | Docker, docker-compose |

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

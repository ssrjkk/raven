# Raven AI

Self-hosted AI assistant framework combining an autonomous coding agent (RavenCode) with multi-channel communication and a web dashboard.

**Status:** Active development | **Tests:** 4,677+ | **Python:** 3.11+ | **License:** MIT

---

## Overview

Raven is a 2-in-1 system:

- **RavenCode** — Autonomous coding agent with LSP auto-enrichment, multi-session execution, plan/safe modes and 50+ dedicated tools (file ops, git, LSP, sandbox, checkpoints)
- **RavenFlow** — Persistent gateway with multi-agent routing, WebSocket streaming, session management and tool orchestration

15 messaging channels including Telegram, Discord, Slack, WhatsApp, Matrix, Teams, and a built-in web interface.

---

## Key Features

**Core Capabilities:**
- Autonomous code generation, refactoring and debugging
- LSP auto-enrichment (Python, TypeScript, Go, Rust)
- Multi-session parallel execution
- Plan/Safe/Fast execution modes
- Canvas visual workspace (code, tables, mermaid diagrams, images)
- RAG memory with semantic search and BM25 keyword retrieval
- Multi-step task planner with tool orchestration
- Scheduled routines and passive monitors (HTTP, price, RSS, file, process)

**Communication:**
- 15 channels: Telegram, Discord, Slack, WhatsApp, Matrix, Teams, Signal, LINE, Feishu, IRC, Google Chat, GitHub, GitLab, email, web chat
- Voice I/O (wake word detection, STT: Whisper/Google/Azure/Vosk, TTS: ElevenLabs/gTTS/Edge)
- WebSocket streaming for real-time updates
- Web dashboard (React SPA) served by the gateway

**LLM Providers:**
- OpenAI, Anthropic, OpenRouter, Ollama, vLLM, Azure, Groq, Bedrock, Vertex AI, Copilot
- Automatic model failover with circuit breaker and rate-limit backoff

**Security:**
- JWT authentication with RBAC
- Tool policy engine (deny/allow per user/channel/session)
- Sandbox profiles (main, non-main, code-exec, web-browsing, read-only)
- Workspace isolation with path traversal protection
- SSRF guard with per-hop redirect validation
- Fernet encryption for secrets
- Audit logging

**Observability:**
- Prometheus metrics
- OpenTelemetry tracing
- Health/readiness probes
- Structured JSON logging via loguru

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Clients & Channels (15)                 │
│  Telegram │ Discord │ Slack │ WhatsApp │ Matrix │ Web UI   │
└──────────────────────────┬─────────────────────────────────┘
                           │ WebSocket/HTTP
┌──────────────────────────▼─────────────────────────────────┐
│                      Raven Gateway (FastAPI)               │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Auth      │→ │  Circuit     │→ │   Rate Limiter    │  │
│  │ (JWT+RBAC)  │  │  Breaker     │  │   (token bucket)  │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Web dashboard (React SPA, served at /)              │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────┬─────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼──────┐  ┌────────▼────┐  ┌──────────▼────┐
│  RavenCode   │  │  Agents     │  │   Routines    │
│    Agent     │  │  Orchestr.  │  │   & Monitors  │
└───────┬──────┘  └────────┬────┘  └──────────┬────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│                 Tool Registry (30+ assistant,              │
│                  50+ coding-agent tools)                   │
│  File │ Bash │ Web │ API │ DB │ Git │ Canvas │ Cron        │
└──────────────────────────┬─────────────────────────────────┘
                           │
        ┌──────────────────┼───────────────┐
┌───────▼──────┐  ┌────────▼─────┐  ┌──────▼──────┐
│  SQLite /    │  │   Vector     │  │  Workspace  │
│  PostgreSQL  │  │   Store      │  │   Files     │
│              │  │  (JSON+BM25) │  │             │
└──────────────┘  └──────────────┘  └─────────────┘

LLM Providers: Ollama → OpenRouter → Anthropic → OpenAI → Groq → ... (failover)
```

The entire system runs as a single Python process (monolith). Optional containers provide
PostgreSQL (`docker-compose.postgres.yml`), NATS (`deploy/docker-compose.nats.yml`) and
observability stack (`docker-compose.monitoring.yml`).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, uvicorn |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, Monaco Editor |
| **Database** | SQLite (default), PostgreSQL (optional) |
| **Vector Store** | JSON embeddings + BM25 (local-first, no external deps) |
| **LLM Providers** | OpenAI, Anthropic, OpenRouter, Ollama, vLLM, Azure, Groq, Bedrock, Vertex AI, Copilot |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio |
| **Voice** | Whisper, Google STT, Azure STT, Vosk, ElevenLabs, gTTS |
| **Security** | JWT (HS256), PBKDF2, Fernet encryption, RBAC |
| **Observability** | OpenTelemetry, Prometheus |
| **Testing** | pytest (4,677+ tests), Vitest |
| **CI/CD** | GitHub Actions (15 workflows) |
| **Deployment** | Docker, docker-compose, systemd |

---

## Quick Start

### Installation

```bash
# From source
git clone https://github.com/ssrjkk/raven.git
cd raven
pip install -e .
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add at least one LLM API key
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
# OPENROUTER_API_KEY=sk-or-...
# GROQ_API_KEY=gsk-...

# Optional: PostgreSQL instead of SQLite
# DATABASE_URL=postgresql://user:pass@localhost:5432/raven
```

### Start

```bash
# Interactive setup wizard (first run)
raven onboard

# Start the gateway
raven start

# Or the AI Gateway bridge
python -m raven aios gateway
```

Open http://localhost:18888/ for the web interface (web UI served by the gateway).

### Docker

```bash
docker compose up -d
```

---

## Usage

### Command Line

```bash
# One-shot agent call
raven agent --message "Create a FastAPI endpoint for user registration"

# Interactive REPL
raven repl

# Textual TUI dashboard
raven tui

# List available LLM models
raven models list
```

### RavenCode

```bash
raven code start --goal "Create a REST API with FastAPI" --project ./my-project

raven@project> create a REST API with FastAPI
# Streams response and executes tools in real-time

raven@project> /help          # Available commands
raven@project> /plan          # Plan-only mode
raven@project> /safe          # Confirm before writes
```

### CLI Reference

```bash
# Core
raven start                    # Start gateway
raven stop                     # Stop gateway
raven status                   # System status
raven doctor                   # Diagnostics
raven onboard                  # Setup wizard
raven init                     # Scaffold raven.json project
raven deploy                   # Generate docker-compose

# Coding
raven code start|status|end    # RavenCode sessions
raven code index <path>        # Index for RAG
raven code search <query>      # Semantic search
raven code review <file>       # AI review

# Agents & tasks
raven agent --message "..."    # One-shot message
raven task list|run|show       # Task engine
raven routine list|add         # Scheduled routines

# Monitoring
raven monitor list|add         # Passive monitors

# Security
raven security audit           # Security audit
raven security audit --deep    # Deep audit

# Database
raven db migrate|backup        # DB management

# LLM & models
raven models list              # Configured models

# Misc
raven history <session_id>     # Session history
raven aios gateway             # AI Gateway bridge
raven backup                   # Memory backup/restore
```

---

## Configuration

### Environment Variables

```bash
# LLM API Keys (required: at least one)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...
GROQ_API_KEY=gsk-...
OLLAMA_BASE_URL=http://localhost:11434
VLLM_BASE_URL=                 # vLLM / OpenAI-compatible local server

# Default model (auto-discovered when empty)
DEFAULT_MODEL=openrouter/openai/gpt-4o

# Critical-thinking model (Truthful Orchestrator, CoV)
RAVEN_CRITICAL_MODEL=
RAVEN_CRITICAL_PROVIDER=

# Master key for secrets encryption
RAVEN_MASTER_KEY=

# Database (optional, defaults to SQLite file data/raven.db)
DATABASE_URL=postgresql://user:pass@localhost:5432/raven

# Web UI
WEB_PORT=18888
WEB_SECRET_KEY=generate-with-secrets-token-hex-32

# Security
TOOLS_PROFILE=messaging  # messaging, minimal, full
EXEC_SECURITY=deny       # deny, ask, full
WORKSPACE_ONLY=true
DM_POLICY=pairing        # pairing, closed, open

# Sandbox
SANDBOX_MODE=non-main    # main, non-main, all, none
SANDBOX_BACKEND=subprocess  # subprocess, docker, none

# Agent workspace
WORKSPACE_PATH=workspace

# Logging
LOG_LEVEL=INFO           # DEBUG, INFO, WARNING, ERROR
LOG_FILE=data/raven.log
```

The `.env` file is discovered from (highest precedence first): the project directory,
`~/.raven/.env`, and the raven install root.

---

## Project Structure

```
raven/
├── raven/                       # Core package
│   ├── channels/                # 15 channel implementations
│   ├── cli/                     # Click-based CLI (26 command groups)
│   ├── coding/                  # Coding assistant, git integration
│   ├── core/
│   │   ├── auth/                # JWT, RBAC, OAuth, password hashing
│   │   ├── security/            # Policy engine, sandbox, SSRF, PII redaction
│   │   ├── task_engine/         # Planner, executor
│   │   ├── monitor/             # HTTP, price, RSS, file, process monitors
│   │   ├── rag/                 # Embeddings, BM25, JSON vector store
│   │   ├── llm/                 # LLM providers with failover + circuit breaker
│   │   ├── gateway/             # RavenFlow gateway
│   │   └── config.py            # Pydantic settings + env cascade
│   ├── gateway/                 # Gateway glue, channel guardian
│   ├── plugins/                 # 10 built-in plugins (api, browser, cron, git…)
│   ├── routines/                # Scheduled routines engine
│   ├── tools/                   # 30+ assistant tools
│   ├── tui/                     # Textual TUI
│   ├── voice/                   # STT, TTS, wake word
│   └── workspace/               # Workspace manager, plugin loader
├── ravencode/                   # Autonomous coding agent
│   ├── runtime/                 # ReActAgent, LSP, multi-session, 50+ tools
│   ├── agents/                  # Orchestrator, sub-agents
│   └── cli/                     # ravencode CLI
├── aios/                        # Thin FastAPI bridge (AI Gateway)
├── web/                         # React 19 + Vite dashboard (SPA)
├── deploy/                      # Docker, systemd, observability, traefik
├── docs/                        # Developer documentation
├── scripts/                     # Build/launch tooling
└── tests/                       # pytest (unit + integration + e2e)
```

---

## Development

### Setup

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven

# Install development dependencies
pip install -e ".[dev]"

# Web frontend
cd web && npm install && cd ..

# Run the full validation gate (ruff + mypy + imports + all tests)
python scripts/check_all.py

# Quick gate (lint + types + imports only, no tests)
python scripts/check_all.py --quick
```

### Code Standards

- **Type hints:** Required for all functions (mypy, 0 errors)
- **Linting:** ruff, 17 rule categories (S, TRY, RET, PTH, PERF, …)
- **Logging:** loguru only, never `print`
- **Async-first:** all I/O operations async
- **Tests:** required for all features; regression-focused
- **Commits:** Conventional Commits format

### Testing

```bash
# All tests
pytest

# Single component
pytest tests/core/test_config.py -q

# E2E tests (marked)
pytest tests/e2e/ -m e2e
```

---

## Deployment

### Docker Compose

```bash
docker compose up -d
```

### Systemd

```bash
sudo cp deploy/raven.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now raven
```

### macOS launchd

```bash
cp deploy/com.raven.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.raven.plist
```

### Containers for optional services

```bash
docker compose -f docker-compose.postgres.yml up -d      # PostgreSQL
docker compose -f docker-compose.monitoring.yml up -d    # Prometheus + Grafana
docker compose -f deploy/docker-compose.nats.yml up -d   # NATS
```

---

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Check what's using the port
netstat -ano | findstr :18888   # Windows
lsof -i :18888                  # macOS/Linux

# Change port in .env
WEB_PORT=18889
```

**LLM API errors:**
- Verify API keys in `.env`
- Run `raven models list` to see configured providers
- Check rate limits and quotas; try a different provider

**Database connection failed:**
```bash
# PostgreSQL: verify DATABASE_URL format
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Check PostgreSQL is running
systemctl status postgresql
```

### Logs

```bash
tail -f data/raven.log
```

### Diagnostics

```bash
raven doctor
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [AGENTS.md](AGENTS.md) for agent conventions.

---

## License

MIT License - see [LICENSE](LICENSE) file.

---

## Contact

- **GitHub:** https://github.com/ssrjkk/raven
- **Issues:** https://github.com/ssrjkk/raven/issues

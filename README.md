
# Raven AI

Enterprise-grade self-hosted AI agent framework combining autonomous coding capabilities with multi-channel communication.

**Status:** Active development | **Tests:** 4,593+ | **Python:** 3.11+ | **License:** MIT

---

## Overview

Raven is a 2-in-1 system:

- **RavenCode** - Autonomous coding agent with LSP auto-enrichment, parallel multi-session, 30+ tools
- **RavenFlow** - Persistent workflow gateway with multi-agent routing, WebSocket streaming, session management

Supports 25+ communication channels including Telegram, Discord, Slack, WhatsApp, Matrix, Teams, and web interface.

---

## Key Features

**Core Capabilities:**
- Autonomous code generation, refactoring, and debugging
- LSP auto-enrichment (Python, TypeScript, Go, Rust)
- Parallel multi-session execution
- Plan/Safe/Fast execution modes
- Canvas visual workspace (code, tables, mermaid diagrams, images)
- RAG memory with semantic search (Qdrant vector store)
- Multi-step task planner with tool orchestration
- Distributed node execution

**Communication:**
- 25+ channels (Telegram, Discord, Slack, WhatsApp, Matrix, Teams, IRC, Signal, LINE, Feishu, web chat, email, SMS)
- Voice I/O (wake word detection, STT: Whisper/Google/Azure/Vosk, TTS: ElevenLabs/gTTS/Edge)
- WebSocket streaming for real-time updates

**Security:**
- JWT authentication with RBAC (4 roles, 16 permissions)
- Tool policy engine (deny/allow per user/channel/session)
- 5 sandbox profiles (main, non-main, code-exec, web-browsing, read-only)
- Workspace isolation with path traversal protection
- Fernet encryption for secrets
- Audit logging (20 event types)

**Monitoring & Automation:**
- HTTP, price, RSS, file, and process monitors
- Scheduled routines (morning briefings, email checks, file organization)
- Custom alerts across all channels

**Observability:**
- Prometheus metrics
- OpenTelemetry tracing
- Grafana dashboards
- Health/readiness probes

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Clients & Channels                      │
│  Telegram │ Discord │ Slack │ WhatsApp │ Matrix │ Web UI     │
└──────────────────────┬──────────────────────────────────────┘
                       │ WebSocket/HTTP
┌──────────────────────▼──────────────────────────────────────┐
│                        Raven Gateway                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │   Auth      │  │   Circuit    │  │   Rate Limiter    │  │
│  │  Middleware │→ │   Breaker    │→ │                   │  │
│  │ (JWT+RBAC)  │  │              │  │                   │  │
│  └─────────────┘  └──────────────┘  └───────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
│  RavenCode   │ │RavenFlow │ │   Custom   │
│    Agent     │ │  Agent   │ │   Agents   │
└───────┬──────┘ └────┬─────┘ └─────┬──────┘
        │              │              │
        └──────────────┼──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                      Tool Registry (30+)                     │
│  File ops │ Bash │ Web │ API │ DB │ Canvas │ Nodes │ Cron   │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
│   SQLite/    │ │  Qdrant  │ │   File     │
│  PostgreSQL  │ │  Vector  │ │   System   │
│              │ │  Store   │ │            │
└──────────────┘ └──────────┘ └────────────┘

LLM Providers: Ollama (local) → OpenRouter → Anthropic → OpenAI (failover)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, uvicorn |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, Monaco Editor |
| **Database** | SQLite (default), PostgreSQL (optional) |
| **Vector Store** | Qdrant, fallback to in-memory |
| **LLM Providers** | Ollama, OpenRouter, Anthropic, OpenAI |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio |
| **Voice** | Whisper, Google STT, Azure STT, Vosk, ElevenLabs, gTTS |
| **Security** | JWT (HS256), bcrypt, Fernet encryption, RBAC |
| **Observability** | OpenTelemetry, Prometheus, Grafana, Jaeger |
| **Message Broker** | NATS + JetStream (optional) |
| **Testing** | pytest (4,593+ tests), Allure, Vitest |
| **CI/CD** | GitHub Actions, Codecov, Docker |
| **Deployment** | Docker, docker-compose, systemd, Kubernetes |

---

## Quick Start

### Installation

```bash
# From PyPI
pip install raven-agent

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

# Optional: PostgreSQL instead of SQLite
# DATABASE_URL=postgresql://user:pass@localhost:5432/raven
```

### Start

```bash
# Interactive setup wizard (first run)
raven onboard

# Start all services
raven start
```

Open http://localhost:18888 for web interface.

### Docker

```bash
docker run -d \
  --name raven \
  -p 18888:18888 \
  -p 18789:18789 \
  -e OPENAI_API_KEY=sk-... \
  -v raven-data:/app/data \
  ssrjkk/raven:latest
```

---

## Usage

### Command Line

```bash
# Coding tasks
raven "Create a FastAPI endpoint for user registration"
raven "Refactor authentication module to use JWT"
raven "Find and fix the bug in test_users.py"

# Code review
raven code review src/auth.py

# Interactive mode
raven code --project ./my-project
```

### RavenCode REPL

```bash
raven code --project ./my-project

raven@project> create a REST API with FastAPI
# Streams response and executes tools in real-time

raven@project> /help          # Available commands
raven@project> /plan          # Plan-only mode
raven@project> /safe          # Confirm before writes
raven@project> /parallel      # Enable multi-session
```

### CLI Reference

```bash
# Core
raven start                    # Start services
raven stop                     # Stop services
raven status                   # System status
raven doctor                   # Diagnostics
raven onboard                  # Setup wizard

# Coding
raven code                     # Interactive REPL
raven code --project <dir>     # Project directory
raven code --plan              # Plan-only mode
raven code --safe              # Safe mode
raven code --parallel          # Multi-session
raven code index <path>        # Index for RAG
raven code search <query>      # Semantic search
raven code review <file>       # AI review

# Tasks
raven task list                # List tasks
raven task run <goal>          # Run task
raven task show <id>           # Task details
raven task cancel <id>         # Cancel task

# Monitoring
raven monitor list             # List monitors
raven monitor add <type> <target>  # Add monitor

# Security
raven security audit           # Security audit
raven security audit --deep    # Deep audit
raven security audit --fix     # Auto-fix

# Database
raven db migrate               # Run migrations
raven db backup                # Create backup
raven db restore <file>        # Restore backup
```

---

## Configuration

### Environment Variables

```bash
# LLM API Keys (required: at least one)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...
OLLAMA_BASE_URL=http://localhost:11434

# Database (optional, defaults to SQLite)
DATABASE_URL=postgresql://user:pass@localhost:5432/raven

# Web UI
WEB_PORT=18888
WEB_SECRET_KEY=generate-with-secrets-token-hex-32

# RavenFlow Gateway
RAVENFLOW_PORT=18789

# Security
TOOLS_PROFILE=messaging  # messaging, coding, full
EXEC_SECURITY=deny  # deny, ask, full
WORKSPACE_ONLY=true

# Observability
METRICS_PORT=9090
OTLP_ENDPOINT=http://localhost:4317

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
JSON_LOG=true
LOG_FILE=data/raven.log
```

### Channel Configuration

Edit `config/channels.yaml`:

```yaml
telegram:
  enabled: true
  bot_token: "123456:ABC..."
  allowed_users:
    - 123456789

discord:
  enabled: true
  bot_token: "MTIz..."
  guild_id: "123456789"

slack:
  enabled: true
  bot_token: "xoxb-..."
  signing_secret: "abc..."
```

---

## Project Structure

```
raven/
├── raven/                      # Core package
│   ├── agent/                  # ReAct agent, multi-agent registry
│   ├── gateway/                # RavenFlow daemon, routing, WebSocket
│   ├── core/
│   │   ├── auth/               # JWT, RBAC, API tokens
│   │   ├── security/           # Policy engine, sandbox, PII redaction
│   │   ├── task_engine/        # Planner, executor
│   │   ├── monitor/            # HTTP, price, RSS, file, process monitors
│   │   ├── rag/                # Embeddings, chunking, vector store
│   │   ├── llm.py              # LLM providers with failover
│   │   └── config.py           # Pydantic settings
│   ├── channels/               # 25+ channel implementations
│   ├── cli/                    # Command-line interface
│   ├── tools/                  # Canvas, Nodes, Plugin tools
│   ├── tui/                    # Terminal UI (textual)
│   ├── voice/                  # STT, TTS, wake word
│   └── workspace/              # Workspace manager, plugin loader
├── ravencode/                  # Autonomous coding agent
│   ├── runtime/
│   │   ├── agent_core.py       # ReActAgent, tool orchestration
│   │   ├── lsp.py              # LSP auto-enrichment
│   │   ├── multisession.py     # Parallel sessions
│   │   └── tools.py            # Tool registry (read, write, edit, bash)
│   ├── cli/                    # ravencode CLI
│   ├── agents/                 # Agent orchestration
│   ├── api/                    # OpenAI-compatible API
│   └── mcp/                    # MCP protocol support
├── web/                        # React 19 + Vite dashboard
├── deploy/                     # Docker, k8s, systemd configs
├── tests/                      # pytest tests (unit + integration + e2e)
└── plugins/                    # User plugins
```

---

## Development

### Setup

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=raven --cov-report=html

# Linting
ruff check .

# Type checking
mypy .
```

### Code Standards

- **Python:** PEP 8, ruff for linting
- **Type hints:** Required for all functions (mypy --strict)
- **Tests:** Required for all features (target: 90%+ coverage)
- **Commits:** Conventional Commits format

### Testing

```bash
# All tests
pytest

# Specific test file
pytest tests/test_agent.py

# With coverage
pytest --cov=raven --cov-report=term-missing

# Parallel execution
pytest -n auto
```

---

## Deployment

### Docker Compose

```bash
docker-compose up -d
```

### Systemd

```bash
# Install service
sudo cp deploy/systemd/raven.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable raven
sudo systemctl start raven
```

### Kubernetes

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
```

---

## Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Check what's using the port
lsof -i :18888

# Change port in .env
WEB_PORT=18889
```

**LLM API errors:**
- Verify API keys in `.env`
- Check rate limits and quotas
- Try different provider (OpenRouter, Anthropic, OpenAI)

**Database connection failed:**
```bash
# For PostgreSQL, verify DATABASE_URL format
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Check PostgreSQL is running
systemctl status postgresql
```

### Logs

```bash
# View logs
tail -f data/raven.log

# Systemd logs
journalctl -u raven -f
```

### Diagnostics

```bash
raven doctor
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) file.

---

## Contact

- **GitHub:** https://github.com/ssrjkk/raven
- **Issues:** https://github.com/ssrjkk/raven/issues
- **Email:** ray013lefe@gmail.com

---

**Copyright (c) 2024-2026 ssrjkk**
```

---

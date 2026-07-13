<div align="center">
  <h1>Raven AI</h1>
  <p><i>2-in-1: <b>RavenCode</b> (opencode analog — autonomous coding agent) + <b>RavenFlow</b> (openclaw analog — persistent workflow gateway). 25+ channels. Task engine. Monitors. RAG. Voice. Web dashboard.</i></p>

  <a href="#features">Features</a> •
  <a href="#quickstart">Quickstart</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#license">License</a>

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

<p align="center">
  <img src="https://img.shields.io/badge/status-active--development-brightgreen" alt="Status">
  <img src="https://img.shields.io/github/stars/ssrjkk/raven?style=social" alt="Stars">
</p>

---

## Demo

<p align="center">
  <i>📺 See Raven in action (30s demo GIF — coming soon)</i>
</p>

```text
$ raven "explain this codebase and fix the failing test"
🐦 Raven is analyzing your project...
   → LSP enrichment: 3 languages detected
   → Planning debug session...
   → Running pytest — found 1 failure
   → Fixing assertion in test_users.py
   → PR opened: #42

$ raven
🐦 Interactive REPL — type your task or /help
  >
```

---

## Why Raven AI?

**Raven AI** is not just a bot. It's a full enterprise-grade automated AI assistant running 24/7 on your server.

It thinks. It plans. It acts. It speaks. It flows.

- **Communicates across 25+ channels** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, web chat + 15 more
- **RavenCode agent** — autonomous coding agent (`ravencode`) with LSP auto-enrichment, parallel multi-session, plan/safe/fast modes, 30+ tools
- **RavenFlow gateway** — persistent workflow daemon (`ravenflow`) with multi-agent routing, WebSocket streaming, session management
- **Canvas visual workspace** — render rich components (code, tables, mermaid diagrams, images, alerts) in terminal or browser
- **Nodes distributed execution** — register, unregister, broadcast and execute across remote nodes
- **Voice I/O** — wake word detection ("Raven", "Hey Raven"), STT (Whisper/Google/Azure/Vosk), TTS (ElevenLabs/gTTS/system/Edge)
- **Executes tasks** — builds a plan from steps, executes each with a tool, returns the result
- **Runs monitors** — pings websites, checks prices, RSS, files, processes and sends alerts
- **Scheduled routines** — morning briefings, email checks, file organization
- **RAG memory** — semantic search across documents, PDF/code chunking, conversation memory
- **Web dashboard** — React 19 + Monaco IDE + Tailwind dashboard
- **Multi-user + RBAC** — admins, users, viewers with role-based access control
- **Security policies** — 5 sandbox profiles (main, non-main, code-exec, web-browsing, read-only), tool allow/deny per session

---

## Quickstart

```bash
pip install raven-agent
# Or for development: pip install -e .
cp .env.example .env
# Edit .env — add at least one LLM API key
raven onboard   # Interactive setup wizard (LLM, Telegram, channels)
raven start     # Start the full platform

# Or use standalone entry points:
ravencode tui   # RavenCode — interactive coding agent
ravenflow       # RavenFlow — persistent workflow gateway
```

### Ports

| Port | Service | Description |
|------|---------|-------------|
| **18888** | Web UI | Web chat, Dashboard, Monaco IDE, Settings |
| **18789** | RavenFlow Gateway | Multi-agent orchestrator daemon with WebSocket streaming |

Open in your browser:
- **http://localhost:18888** — web chat
- **http://localhost:18888/dashboard** — dashboard
- **http://localhost:18888/ide** — Monaco editor with AI sidebar

### Docker

```bash
docker compose up
```

### Web Dashboard (development)

```bash
cd web
npm install
npm run dev    # http://localhost:5173 (proxies to :18888)
```

---

## Comparison

| Feature | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|---------|----------|-----------------|---------|---------|---------|
| Self-hosted | ✅ 100% | ✅ | ❌ cloud | ❌ cloud | ❌ cloud |
| 25+ channels | ✅ | ❌ | ❌ | ✅ web only | ❌ |
| Coding agent with LSP | ✅ | ❌ | ❌ | ❌ | ✅ basic |
| Multi-agent orchestration | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| Voice I/O + wake word | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| Monitors & alerts | ✅ | ❌ | ❌ | ❌ | ❌ |
| Scheduled routines | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG (local-first) | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBAC multi-user | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5 sandbox profiles | ✅ | ❌ | ❌ | ❌ | ❌ |
| Canvas workspace | ✅ | ❌ | ❌ | ❌ | ❌ |
| Nodes distributed exec | ✅ | ❌ | ❌ | ❌ | ❌ |
| Offline mode | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| Web dashboard | ✅ React + Monaco | ❌ CLI only | ❌ | ✅ | ✅ IDE |
| Open source | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| Free | ✅ | ✅ | ✅ | ❌ $20/mo | ❌ $10/mo |

---

## Features

| Feature | Description |
|---------|-------------|
| **25+ channels** | Telegram (voice→text via Whisper, inline buttons), Discord (slash commands + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat + 15 more (Telegram API, Discord API, Slack RTM, WhatsApp Cloud, Matrix CS, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat, Email IMAP, SMS Twilio, Alexa, Google Home, Discord Webhook, Telegram Webhook, Custom Webhook) |
| **RavenFlow Gateway** | Persistent workflow daemon (`ravenflow`) on port 18789 with multi-agent routing engine, session management, WebSocket streaming, channel-origin dispatch, sandbox policies |
| **RavenCode Agent** | Autonomous coding agent (`ravencode`) — interactive REPL with prompt input, streaming responses, inline tool calls, LSP enrichment. Commands: `/multisession`, `/plan`, `/safe`, `/fast`, `/enrich`, `/exit` |
| **LSP Auto-Enrichment** | `enrich_context()` scans project, detects languages, starts LSP servers (pyright, typescript-language-server, gopls, rust-analyzer), gathers document symbols |
| **Parallel Multi-Session** | `SessionManager` with concurrent `ManagedSession` tasks, abort/cleanup, singleton pattern |
| **Canvas Visual Workspace** | Render rich components: text, code blocks, tables, mermaid diagrams, links, images, lists, alerts. Output to terminal or browser HTML |
| **Nodes Distributed Execution** | Register/unregister remote nodes, execute tasks across nodes, broadcast to all registered endpoints |
| **Voice I/O** | Wake word detection ("Raven", "Hey Raven", "OK Raven"), STT (Whisper, Google, Azure, Vosk), TTS (ElevenLabs, gTTS, system SAPI, Edge), microphone recording |
| **Sandbox Security Policy** | 5 policies (main, non-main, code-exec, web-browsing, read-only) with tool allow/deny, network controls, resource limits. Changeable at runtime |
| **Cron / Scheduling** | Schedule recurring tasks via `cron_schedule`/`cron_list`/`cron_cancel` tools (APScheduler-backed) |
| **Unified Launcher** | `main.py` — starts all services (Raven, RavenFlow, Web UI) with graceful shutdown |
| **Task Engine** | Multi-step planner — LLM breaks goals into steps, selects tools, executes, returns results |
| **Monitor Engine** | 5 monitor types: HTTP(S), asset price, RSS feed, file/directory, process. Trigger conditions, alerts, check history |
| **Routines** | Automated scheduled routines: send_briefing, check_email, organize_files, send_message |
| **RAG Knowledge Base** | Embedding engine (OpenAI + local), vector storage, document chunking (PDF/TXT/code), semantic retrieval |
| **Workspace Skills** | Skills in `workspace/skills/`: crypto, morning briefing, web search. Auto-loaded via SKILL.md |
| **Web Dashboard + IDE** | React 19 + Vite + Tailwind + Monaco Editor: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings, IDE (editor + terminal + AI sidebar) |
| **Auth & RBAC** | Multi-user authentication, 4 roles (admin/user/viewer/banned), 16 permissions, Bearer tokens |
| **Enterprise infrastructure** | Circuit breaker, HTTP pool, rate limiter, retry with exponential backoff, audit log (20 event types), Prometheus metrics, health checks |
| **Plugin system** | 10 plugins — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox with capability-based control |
| **Safety** | DM pairing, channel allowlist, Fernet secret encryption, rate limiting, subprocess/Docker sandbox |
| **Security Policy** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow priority, workspaceOnly FS, contextVisibility, sanitize_external_content, security audit CLI |

---

## CLI

```
raven start                    Start gateway
raven stop                     Stop
raven status                   System status
raven doctor                   Diagnostics
raven onboard                  Setup wizard
raven agent --message ...      Send message to agent
raven pairing list             Pairing requests
raven pairing approve CODE     Confirm user
raven models list              Available models
raven plugins list             Loaded plugins
raven history SESSION_ID       Message history
raven db migrate               DB migrations
raven db backup                DB backup
raven task list                List tasks
raven task run <goal>          Run task
raven task show <id>           Task details
raven task cancel <id>         Cancel task
raven monitor list             List monitors
raven monitor add ...          Add monitor
raven code                     Interactive coding REPL
raven code --project <dir>     Start REPL in project directory
raven code --plan              Plan-only mode (no writes)
raven code --safe              Safe mode (confirmations on writes)
raven code --parallel          Enable parallel multi-session
raven code index <path>        Index code
raven code search <query>      Search code
raven code review <file>       Review file
raven routine list             List routines
raven routine add ...          Add routine
raven security audit           Security check
raven security audit --deep    Deep check (network, env, dependencies)
raven security audit --fix     Auto-fix issues
raven flow serve --port 18789  Start RavenFlow gateway daemon
raven flow ask <message>       Send message to running gateway
raven flow sessions            List active Flow sessions

ravencode tui                  Start interactive TUI
ravencode serve                Start headless HTTP server
ravencode web                  Start web interface
ravencode session list         List saved sessions
ravencode auth login           Configure API key

ravenflow --port 18789         Start RavenFlow gateway daemon
ravenflow serve --port 18789   Start RavenFlow gateway daemon
```

## Chat Commands

```
/status               Bot status
/new                  New conversation
/reset                Reset session
/compact              Compress history
/task <goal>          Execute task
/monitor list         List monitors
/monitor add <type> <target>  Add monitor
/code index [path]    Index code
/code search <query>  Search code
/code review <file>   Review file
/routine list         List routines
/routine add <action> <sched>  Add routine
/help                 All commands
/pair <code>         Pair user
```

---

## Architecture

```mermaid
flowchart TB
    subgraph Clients["Clients & Channels"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["Core System"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["Observability"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["Data Layer"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM Providers"]
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

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite |
| **LLM** | Ollama (local) → OpenRouter → Anthropic → OpenAI (failover) |
| **Memory** | SQLite + ChromaDB + numpy vector store |
| **RAG** | Qdrant vector store, fallback in-memory, n-gram embedding |
| **Auth** | bcrypt, JWT (HS256), RBAC (4 roles, 16 permissions) |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI daemon (port 18789), routing engine, WebSocket streaming, multi-agent dispatch |
| **RavenCode** | Interactive REPL, LSP auto-enrichment (pyright/tsserver/gopls/rust-analyzer), parallel multi-session, plan/safe/fast modes, 30+ tools |
| **Canvas** | Rich component rendering (code, table, mermaid, image, link, list, alert), HTML + browser output |
| **Nodes** | Distributed node registry, broadcast execution, async HTTP dispatch |
| **Voice** | WakeWordDetector (speech_recognition), Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **Sandbox Policy** | 5 policy profiles (main/non-main/code-exec/web-browsing/read-only), runtime tool allow/deny |
| **Message Broker** | NATS + JetStream (optional, for distributed mode) |
| **Resilience** | Circuit breaker, rate limiter, retry with exponential backoff, audit log (20 event types), Prometheus metrics, health checks |
| **Observability** | OpenTelemetry (traces + metrics), health/ready probes |
| **Security** | Rate limiting, JWT auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy (deny/ask/full), contextVisibility, workspace isolation, security audit CLI |
| **CI/CD** | GitHub Actions — parallel lint + typecheck + test, Allure reporting, Codecov |
| **Deploy** | Docker, docker-compose, systemd |
| **Testing** | pytest (800+ tests, Allure reporting), Vitest (React) |

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
# Start the gateway (standalone command)
ravenflow --port 18789

# Or via main CLI
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

### Unified Launcher

A single `main.py` launcher starts all services:
```bash
python main.py --web-port 5173 --flow-port 18789
```

---

## Contact

<div align="center">
  <p>
    <b>Raven AI</b> — developed by <a href="https://github.com/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    Have an idea or bug? → <a href="https://github.com/ssrjkk/raven/issues">Open an issue</a>
  </p>
  <p>
    Want to contribute? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>Built for developers who need their personal AI 24/7</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

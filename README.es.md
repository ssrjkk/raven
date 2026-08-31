<div align="center">
  <h1>Raven AI</h1>
  <p><i>2-en-1: <b>RavenCode</b> (alternativa a opencode — agente de codificación autónomo) + <b>RavenFlow</b> (alternativa a openclaw — gateway de flujo de trabajo persistente). 25+ canales. Tareas. Monitores. RAG. Voz. Panel web.</i></p>

  <a href="#features">Características</a> •
  <a href="#quickstart">Inicio rápido</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">Arquitectura</a> •
  <a href="#tech-stack">Stack tecnológico</a> •
  <a href="#license">Licencia</a>

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
  [![Hybrid](https://img.shields.io/badge/2--in--1-ravencode+%2B+ravenflow-orange)]()

  [English](README.md) •
  [Русский](README.ru.md) •
  [简体中文](README.zh.md) •
  [한국어](README.ko.md) •
  [Español](README.es.md) •
  [日本語](README.ja.md) •
</div>

---

## Por qué Raven AI?

**Raven AI** no es solo un bot. Es un asistente de IA automatizado de nivel empresarial que funciona 24/7 en tu servidor.

Piensa. Planifica. Actúa.

- **Se comunica en 12 mensajeros** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE + chat web
- **Ejecuta tareas** — construye un plan en pasos, ejecuta cada uno con una herramienta, devuelve el resultado
- **Monitorea** — verifica sitios web, precios, RSS, archivos, procesos y envía alertas
- **Escribe código** — indexa bases de código, busca símbolos, revisa archivos, gestiona sesiones de desarrollo
- **Rutinas programadas** — informes matutinos, revisión de correo, organización de archivos
- **Memoria RAG** — búsqueda semántica en documentos, chunking de PDF/código, memoria de conversaciones
- **Panel web** — interfaz React con monitoreo, gestión de tareas, monitores y rutinas
- **Multi-usuario + RBAC** — administradores, usuarios, visores con control de acceso basado en roles

---

## Inicio rápido

`ash
pip install raven-agent
# O para desarrollo: pip install -e .
cp .env.example .env
# Edita .env — añade al menos una clave API de LLM
raven onboard   # Asistente de configuración interactivo (LLM, Telegram, canales)
raven start
`

### Puertos

| Puerto | Servicio | Descripción |
|--------|----------|-------------|
| **18888** | Web UI | Chat web, panel, Monaco IDE, configuración |
| **18789** | RavenFlow Gateway | Daemon orquestador multi-agente con streaming WebSocket |

Abre en tu navegador:
- **http://localhost:18888** — chat web
- **http://localhost:18888/dashboard** — panel
- **http://localhost:18888/ide** — Editor Monaco con panel AI

### Docker

`ash
docker compose up
`

### Panel web (desarrollo)

`ash
cd web
npm install
npm run dev    # http://localhost:5173 (proxy a :18888)
`

---

## Características

| Característica | Descripción |
|---------------|-------------|
| **25+ canales** | Telegram (voz→texto con Whisper, botones inline), Discord (comandos / + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat |
| **Motor de tareas** | Planificador multi-paso — LLM divide objetivos en pasos, selecciona herramientas, ejecuta, devuelve resultados |
| **Motor de monitores** | 5 tipos: HTTP(S), precio de activo, feed RSS, archivo/directorio, proceso. Condiciones de activación, alertas, historial |
| **Asistente de código** | Indexación (AST, 8 lenguajes), búsqueda semántica, revisión de archivos (LLM-driven), sesiones de desarrollo |
| **Rutinas** | Automáticas programadas: send_briefing, check_email, organize_files, send_message |
| **Base RAG** | Motor de embeddings (OpenAI + local), almacenamiento vectorial, chunking (PDF/TXT/código), recuperación semántica |
| **Skills de workspace** | Skills en workspace/skills/: cripto, briefing, búsqueda web. Carga automática via SKILL.md |
| **Panel web** | React 19 + Vite + Tailwind: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings |
| **Auth & RBAC** | Autenticación multi-usuario, 4 roles (admin/user/viewer/banned), 16 permisos, tokens Bearer |
| **Infraestructura enterprise** | Circuit breaker, pool HTTP, limitador de tasa, reintento con backoff exponencial, log de auditoría (20 tipos), métricas Prometheus, health checks |
| **Sistema de plugins** | 10 plugins — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox con control basado en capacidades |
| **Seguridad** | DM pairing, lista blanca de canales, cifrado Fernet, limitación de tasa, sandbox subprocess/Docker |
| **Política de seguridad** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow priority, workspaceOnly FS, contextVisibility, sanitize_external_content, CLI de auditoría |

---

## CLI

`
raven start                    Iniciar gateway
raven stop                     Detener
raven status                   Estado del sistema
raven doctor                   Diagnóstico
raven onboard                  Asistente de configuración
raven agent --message ...      Enviar mensaje al agente
raven pairing list             Solicitudes de vinculación
raven pairing approve CODE     Confirmar usuario
raven models list              Modelos disponibles
raven plugins list             Plugins cargados
raven history SESSION_ID       Historial de mensajes
raven db migrate               Migraciones BD
raven db backup                Respaldo BD
raven task list                Lista de tareas
raven task run <goal>          Ejecutar tarea
raven task show <id>           Detalles de tarea
raven task cancel <id>         Cancelar tarea
raven monitor list             Lista de monitores
raven monitor add ...          Añadir monitor
raven code index <path>        Indexar código
raven code search <query>      Buscar código
raven code review <file>       Revisar archivo
raven routine list             Lista de rutinas
raven routine add ...          Añadir rutina
raven security audit           Auditoría de seguridad
raven security audit --deep    Auditoría profunda (red, env, dependencias)
raven security audit --fix     Auto-corregir problemas
`

## Comandos de chat

`
/status               Estado del bot
/new                  Nueva conversación
/reset                Reiniciar sesión
/compact              Comprimir historial
/task <goal>          Ejecutar tarea
/monitor list         Lista de monitores
/monitor add <type> <target>  Añadir monitor
/code index [path]    Indexar código
/code search <query>  Buscar código
/code review <file>   Revisar archivo
/routine list         Lista de rutinas
/routine add <action> <sched>  Añadir rutina
/help                 Todos los comandos
/pair <code>         Vincular usuario
`

---

## Arquitectura

`mermaid
flowchart TB
    subgraph Clients["Clientes y Canales"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["Sistema Central"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["Observabilidad"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["Capa de Datos"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["Proveedores LLM"]
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
`

## Árbol del proyecto

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

Raven AI includes `ravencode`, a full-featured autonomous coding agent:

```bash
# Start the TUI
ravencode tui

# Start headless HTTP server
ravencode serve

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



## Contacto

<div align="center">
  <p>
    <b>Raven AI</b> — desarrollado por <a href="https://github.com/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a>
  </p>
  <p>
    ¿Tienes una idea o un bug? → <a href="https://github.com/ssrjkk/raven/issues">Abre un issue</a>
  </p>
  <p>
    ¿Quieres contribuir? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>2-en-1: RavenCode + RavenFlow. 25+ canales. Tareas. Monitores. RAG. Voz. Panel web.</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

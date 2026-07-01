<div align="center">
  <h1>Raven AI</h1>
  <p><i>Asistente personal IA enterprise. 25+ canales. RavenFlow. RavenCode. Voz. Canvas. Nodes.</i></p>

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
  [![Tests](https://img.shields.io/badge/tests-859_passing-brightgreen)]()
  [![Coverage](https://img.shields.io/codecov/c/github/ssrjkk/raven?logo=codecov)]()
  [![Security](https://img.shields.io/badge/security-hardened-blueviolet)]()
  [![AI-OS-MVP](https://img.shields.io/badge/aios-mvp-purple)]()
  [![Hybrid](https://img.shields.io/badge/hybrid-web+api+desktop-orange)]()

  [English](README.md) •
  [Русский](README.ru.md) •
  [简体中文](README.zh.md) •
  [繁體中文](README.zht.md) •
  [한국어](README.ko.md) •
  [Deutsch](README.de.md) •
  [Español](README.es.md) •
  [Français](README.fr.md) •
  [Italiano](README.it.md) •
  [Dansk](README.da.md) •
  [日本語](README.ja.md) •
  [Polski](README.pl.md) •
  [العربية](README.ar.md) •
  [Bosanski](README.bs.md) •
  [Norsk](README.no.md) •
  [Português (Brasil)](README.br.md) •
  [ไทย](README.th.md) •
  [Türkçe](README.tr.md) •
  [Українська](README.uk.md) •
  [বাংলা](README.bn.md) •
  [Ελληνικά](README.gr.md) •
  [Tiếng Việt](README.vi.md)
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

Abre en tu navegador:
- **http://localhost:18888** — chat web
- **http://localhost:18888/dashboard** — panel

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

    subgraph Gateway["Capa de Gateway API"]
        GW["Gateway (Go)\n:8000"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT Validation"]
    end

    subgraph Services["Microservicios"]
        AS["Auth Service (Go)\n:8001 — JWT, SQLite, gRPC"]
        AC["Agent Core (Python)\n:8002 — LLM Router"]
        ME["Monitor Engine (Go)\n:8003 — SQLite, NATS"]
        RS["RAG Service (Python)\n:8004 — Qdrant"]
        TE["Task Engine (Python)\n:8005 — SQLite, Outbox, Saga"]
        CS["Code Service (Python)\n:8006 — Sandbox"]
    end

    subgraph Observability["Observabilidad"]
        OTEL["OTel Collector\n:4317 gRPC / :4318 HTTP"]
        TEMPO["Tempo\nTrace Storage"]
        LOKI["Loki\nLog Aggregation"]
        PROM["Prometheus\n:9090"]
        GRAF["Grafana\n:3000 — Dashboards"]
    end

    subgraph Messaging["Broker de Mensajes"]
        NATS["NATS / JetStream\n:4222"]
    end

    subgraph Storage["Capa de Datos"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store :6333"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["Proveedores LLM"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    subgraph AgentSystem["Sistema de Agente"]
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

## Árbol del proyecto

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
| **Backend** | Python 3.13+, FastAPI, asyncio, SQLite (modernc.org/sqlite) |
| **LLM** | Ollama (local) → OpenRouter → Anthropic → OpenAI (failover) |
| **Memory** | SQLite + ChromaDB + numpy vector store |
| **RAG** | Qdrant vector store, fallback in-memory, n-gram embedding |
| **Auth** | bcrypt, JWT (HS256), gRPC, RBAC (4 roles, 16 permissions) |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI daemon (port 18789), routing engine, WebSocket streaming, multi-agent dispatch |
| **RavenCode** | Interactive REPL, LSP auto-enrichment (pyright/tsserver/gopls/rust-analyzer), parallel multi-session, plan/safe/fast modes, 30+ tools |
| **Canvas** | Rich component rendering (code, table, mermaid, image, link, list, alert), HTML + browser output |
| **Nodes** | Distributed node registry, broadcast execution, async HTTP dispatch |
| **Voice** | WakeWordDetector (speech_recognition), Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **Sandbox Policy** | 5 policy profiles (main/non-main/code-exec/web-browsing/read-only), runtime tool allow/deny |
| **Message Broker** | NATS + JetStream (streams: agent.response, monitor.check.completed, task.events, auth.user.created) |
| **Gateway** | Go 1.26 — circuit breaker, rate limiter, auth proxy, gRPC retry, OpenTelemetry |
| **Auth Service** | Go 1.26 — SQLite, JWT, gRPC, token bucket rate limiter, OpenTelemetry |
| **Monitor Engine** | Go 1.26 — HTTP health checks, SQLite, NATS events, Prometheus metrics |
| **Resilience** | Circuit breaker, gRPC retry (exponential backoff), rate limiter, outbox pattern, saga pattern, idempotency |
| **Observability** | OpenTelemetry (traces + metrics), Prometheus, Grafana (12 panels), Loki, Tempo, health/ready probes |
| **Security** | Rate limiting, JWT auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy (deny/ask/full), contextVisibility, workspace isolation, security audit CLI |
| **CI/CD** | GitHub Actions — parallel Go/Python/web lint + test + build, Allure TestOps, Docker buildx, Codecov, Playwright E2E, k6 load tests |
| **Deploy** | Docker (multi-stage, distroless, non-root), docker-compose (microservice stack), Kubernetes manifests, systemd, launchd |
| **Testing** | pytest (800+ tests, Allure reporting), Go table-driven tests, Vitest (React), Playwright (E2E), k6 (load) |

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
  <p><i>Asistente personal IA enterprise. 25+ canales. RavenFlow. RavenCode. Voz. Canvas. Nodes.</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

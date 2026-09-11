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
  <i>📺 Ve a Raven en acción (demo GIF de 30s — próximamente)</i>
</p>

```text
$ raven "explica este código y arregla el test que falla"
🐦 Raven está analizando tu proyecto...
   → Enriquecimiento LSP: 3 lenguajes detectados
   → Planificando sesión de depuración...
   → Ejecutando pytest — encontró 1 fallo
   → Arreglando la aserción en test_users.py
   → PR abierto: #42

$ raven
🐦 REPL interactivo — escribe tu tarea o /help
  >
```

---

## Por qué Raven AI?

**Raven AI** no es solo un bot. Es un asistente de IA automatizado de nivel empresarial que funciona 24/7 en tu servidor.

Piensa. Planifica. Actúa. Habla. Fluye.

- **Se comunica en 25+ mensajeros** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE + chat web y 15 más
- **Agente RavenCode** — agente de codificación autónomo (`ravencode`) con auto-enriquecimiento LSP, multi-sesión en paralelo, modos plan/safe/fast, 30+ herramientas
- **Gateway RavenFlow** — demonio de flujo de trabajo persistente (`ravenflow`) con enrutamiento multi-agente, streaming WebSocket, gestión de sesiones
- **Espacio de trabajo Canvas** — renderiza componentes enriquecidos (código, tablas, diagramas mermaid, imágenes, alertas) en terminal o navegador
- **Ejecución distribuida con Nodes** — registra, desregistra, difunde y ejecuta en nodos remotos
- **Voz** — palabra de activación ("Raven", "Hey Raven"), STT (Whisper/Google/Azure/Vosk), TTS (ElevenLabs/gTTS/system/Edge)
- **Ejecuta tareas** — construye un plan por pasos, ejecuta cada uno con una herramienta, devuelve el resultado
- **Monitorea** — verifica sitios web, precios, RSS, archivos, procesos y envía alertas
- **Rutinas programadas** — informes matutinos, revisión de correo, organización de archivos
- **Memoria RAG** — búsqueda semántica en documentos, chunking de PDF/código, memoria de conversaciones
- **Panel web** — React 19 + Monaco IDE + Tailwind
- **Multi-usuario + RBAC** — administradores, usuarios, visores con control de acceso basado en roles
- **Políticas de seguridad** — 5 perfiles sandbox (main, non-main, code-exec, web-browsing, read-only), allow/deny de herramientas por sesión

---

## Inicio rápido

```bash
pip install raven-agent
# O para desarrollo: pip install -e .
cp .env.example .env
# Edita .env — añade al menos una clave API de LLM
raven onboard   # Asistente de configuración interactivo (LLM, Telegram, canales)
raven start     # Inicia la plataforma completa

# O usa puntos de entrada independientes:
ravencode tui   # RavenCode — agente de codificación interactivo
ravenflow       # RavenFlow — gateway de flujo de trabajo persistente
```

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

```bash
docker compose up
```

### PostgreSQL (opcional, reemplaza SQLite)

Raven por defecto guarda los datos de cada servicio en SQLite. Configura `DATABASE_URL`
(o pasa un DSN `postgresql://` como `db_path` del almacén) para usar PostgreSQL en todos
los almacenes principales (tareas, monitores, rutinas, auth, sesiones, outbox, analítica, persister).

```bash
pip install "raven-agent[postgres]"   # instala asyncpg

# Inicia un Postgres local (user/password/db = raven)
docker compose -f docker-compose.postgres.yml up -d

# En .env
DATABASE_URL=postgresql://raven:raven@localhost:5432/raven
```

Las migraciones se ejecutan automáticamente en la primera conexión; no se migran datos desde SQLite.

### Panel web (desarrollo)

```bash
cd web
npm install
npm run dev    # http://localhost:5173 (proxy a :18888)
```

---

## Comparación

| Característica | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|----------------|----------|------------------|---------|---------|---------|
| Self-hosted | ✅ 100% | ✅ | ❌ nube | ❌ nube | ❌ nube |
| 25+ canales | ✅ | ❌ | ❌ | ✅ solo web | ❌ |
| Agente de código con LSP | ✅ | ❌ | ❌ | ❌ | ✅ básico |
| Orquestación multi-agente | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| Voz + palabra de activación | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| Monitores y alertas | ✅ | ❌ | ❌ | ❌ | ❌ |
| Rutinas programadas | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG (local-first) | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBAC multi-usuario | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5 perfiles sandbox | ✅ | ❌ | ❌ | ❌ | ❌ |
| Espacio Canvas | ✅ | ❌ | ❌ | ❌ | ❌ |
| Ejecución distribuida | ✅ | ❌ | ❌ | ❌ | ❌ |
| Modo offline | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| Panel web | ✅ React + Monaco | ❌ solo CLI | ❌ | ✅ | ✅ IDE |
| Código abierto | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| Gratis | ✅ | ✅ | ✅ | ❌ $20/mes | ❌ $10/mes |

---

## Características

| Característica | Descripción |
|---------------|-------------|
| **25+ canales** | Telegram (voz→texto con Whisper, botones inline), Discord (comandos / + embed), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat + 15 más (Telegram API, Discord API, Slack RTM, WhatsApp Cloud, Matrix CS, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat, Email IMAP, SMS Twilio, Alexa, Google Home, Discord Webhook, Telegram Webhook, Custom Webhook) |
| **Gateway RavenFlow** | Demonio de flujo de trabajo persistente (`ravenflow`) en el puerto 18789 con motor de enrutamiento multi-agente, gestión de sesiones, streaming WebSocket, despacho por canal y políticas sandbox |
| **Agente RavenCode** | Agente de codificación autónomo (`ravencode`) — REPL interactivo con streaming, llamadas de herramientas inline, enriquecimiento LSP. Comandos: `/multisession`, `/plan`, `/safe`, `/fast`, `/enrich`, `/exit` |
| **Auto-enriquecimiento LSP** | `enrich_context()` escanea el proyecto, detecta lenguajes, arranca servidores LSP (pyright, typescript-language-server, gopls, rust-analyzer) y recopila símbolos |
| **Multi-sesión en paralelo** | `SessionManager` con tareas `ManagedSession` concurrentes, abort/cleanup, patrón singleton |
| **Espacio Canvas** | Renderiza componentes enriquecidos: texto, código, tablas, diagramas mermaid, enlaces, imágenes, listas, alertas. Salida a terminal o HTML de navegador |
| **Ejecución distribuida con Nodes** | Regístro/desregistro de nodos remotos, ejecución de tareas, difusión a todos los endpoints registrados |
| **Voz** | Palabra de activación ("Raven", "Hey Raven", "OK Raven"), STT (Whisper, Google, Azure, Vosk), TTS (ElevenLabs, gTTS, SAPI del sistema, Edge), grabación de micrófono |
| **Política de seguridad sandbox** | 5 políticas (main, non-main, code-exec, web-browsing, read-only) con allow/deny de herramientas, control de red, límites de recursos. Cambiables en caliente |
| **Cron / Programación** | Programación de tareas recurrentes vía `cron_schedule`/`cron_list`/`cron_cancel` (basado en APScheduler) |
| **Launcher unificado** | `main.py` — arranca todos los servicios (Raven, RavenFlow, Web UI) con apagado elegante |
| **Motor de tareas** | Planificador multi-paso — LLM divide objetivos en pasos, selecciona herramientas, ejecuta, devuelve resultados |
| **Motor de monitores** | 5 tipos: HTTP(S), precio de activo, feed RSS, archivo/directorio, proceso. Condiciones de activación, alertas, historial |
| **Rutinas** | Automáticas programadas: send_briefing, check_email, organize_files, send_message |
| **Base RAG** | Motor de embeddings (OpenAI + local), almacenamiento vectorial, chunking (PDF/TXT/código), recuperación semántica |
| **Skills de workspace** | Skills en `workspace/skills/`: cripto, briefing, búsqueda web. Carga automática vía SKILL.md |
| **Panel web + IDE** | React 19 + Vite + Tailwind + Monaco Editor: Dashboard, Chat, Tasks, Monitors, Routines, Code Sessions, Settings, IDE (editor + terminal + panel AI) |
| **Auth & RBAC** | Autenticación multi-usuario, 4 roles (admin/user/viewer/banned), 16 permisos, tokens Bearer |
| **Infraestructura enterprise** | Circuit breaker, pool HTTP, limitador de tasa, reintento con backoff exponencial, log de auditoría (20 tipos), métricas Prometheus, health checks |
| **Sistema de plugins** | 10 plugins — browser, code, cron, files, git, memory, api, ocr, process, sessions. Sandbox con control basado en capacidades |
| **Seguridad** | DM pairing, lista blanca de canales, cifrado Fernet, limitación de tasa, sandbox subprocess/Docker |
| **Política de seguridad** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow priority, workspaceOnly FS, contextVisibility, sanitize_external_content, CLI de auditoría |

---

## CLI

```
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
raven code                     REPL de codificación interactivo
raven code --project <dir>     REPL en el directorio del proyecto
raven code --plan              Modo solo plan (sin escrituras)
raven code --safe              Modo seguro (confirmaciones antes de escribir)
raven code --parallel          Habilitar multi-sesión en paralelo
raven code index <path>        Indexar código
raven code search <query>      Buscar código
raven code review <file>       Revisar archivo
raven routine list             Lista de rutinas
raven routine add ...          Añadir rutina
raven security audit           Auditoría de seguridad
raven security audit --deep    Auditoría profunda (red, env, dependencias)
raven security audit --fix     Auto-corregir problemas
raven flow serve --port 18789  Iniciar gateway RavenFlow
raven flow ask <message>       Enviar mensaje al gateway en ejecución
raven flow sessions            Listar sesiones Flow activas

ravencode tui                  TUI interactivo
ravencode serve                Servidor HTTP sin interfaz
ravencode web                  Interfaz web
ravencode session list         Listar sesiones guardadas
ravencode auth login           Configurar clave API

ravenflow --port 18789         Iniciar demonio de gateway RavenFlow
ravenflow serve --port 18789   Iniciar demonio de gateway RavenFlow
```

## Comandos de chat

```
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
/pair <code>          Vincular usuario
```

---

## Arquitectura

```mermaid
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
```

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

## Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| **Backend** | Python 3.11+, FastAPI, asyncio, SQLite (por defecto) + PostgreSQL (opcional) |
| **LLM** | Ollama (local) → OpenRouter → Anthropic → OpenAI (failover) |
| **Memory** | SQLite / PostgreSQL + ChromaDB + numpy vector store |
| **RAG** | Qdrant vector store, fallback in-memory, n-gram embedding |
| **Auth** | bcrypt, JWT (HS256), RBAC (4 roles, 16 permisos) |
| **Frontend** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **Channels** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI daemon (puerto 18789), routing engine, streaming WebSocket, multi-agent dispatch |
| **RavenCode** | REPL interactivo, auto-enriquecimiento LSP (pyright/tsserver/gopls/rust-analyzer), multi-sesión en paralelo, modos plan/safe/fast, 30+ herramientas |
| **Canvas** | Render de componentes enriquecidos (código, tabla, mermaid, imagen, enlace, lista, alerta), salida HTML + navegador |
| **Nodes** | Registro de nodos distribuidos, ejecución broadcast, dispatch HTTP asíncrono |
| **Voz** | WakeWordDetector (speech_recognition), Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **Sandbox Policy** | 5 perfiles de política (main/non-main/code-exec/web-browsing/read-only), allow/deny en runtime |
| **Message Broker** | NATS + JetStream (opcional, para modo distribuido) |
| **Resilience** | Circuit breaker, rate limiter, retry con backoff exponencial, log de auditoría (20 tipos), métricas Prometheus, health checks |
| **Observability** | OpenTelemetry (traces + metrics), health/ready probes |
| **Security** | Rate limiting, JWT auth, DM pairing, Fernet encryption, RBAC, plugin sandbox, ToolPolicyEvaluator (deny/allow), exec security policy (deny/ask/full), contextVisibility, workspace isolation, security audit CLI |
| **CI/CD** | GitHub Actions — parallel lint + typecheck + test, Allure reporting, Codecov |
| **Deploy** | Docker, docker-compose, systemd |
| **Testing** | pytest (4593+ tests, Allure reporting), Vitest (React) |

---

## RavenCode — Agente de codificación de terminal

Raven AI incluye `raven code`, un agente de codificación de terminal interactivo completo:

```bash
# Iniciar el REPL
raven code --project ./my-project

# En el REPL:
raven@project> crea una API REST con FastAPI
# ... transmite la respuesta, hace llamadas de herramientas, edita archivos inline

# Comandos integrados:
/help          Mostrar comandos disponibles
/multisession  Ejecutar subtareas en paralelo
/plan          Modo solo plan (sin escrituras)
/safe          Modo seguro (confirmar antes de escribir)
/fast          Modo rápido (omitir enriquecimiento)
/enrich        Actualizar análisis LSP
/session <id>  Cambiar a una sesión en paralelo
/exit          Salir
```

### Gateway RavenFlow

Demonio orquestador multi-agente con streaming WebSocket:

```bash
# Iniciar el gateway (comando independiente)
ravenflow --port 18789

# O vía el CLI principal
raven flow serve --port 18789

# Enviar un mensaje al agente
raven flow ask "resume el README"

# Listar sesiones activas
raven flow sessions
```

### Espacio de trabajo visual Canvas

Renderiza componentes visuales enriquecidos directamente desde el agente:

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### Launcher unificado

Un único lanzador `main.py` inicia todos los servicios:
```bash
python main.py --web-port 5173 --flow-port 18789
```

---

## Contacto

<div align="center">
  <p>
    <b>Raven AI</b> — desarrollado por <a href="https://github.com/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    ¿Tienes una idea o un bug? → <a href="https://github.com/ssrjkk/raven/issues">Abre un issue</a>
  </p>
  <p>
    ¿Quieres contribuir? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>Hecho para desarrolladores que necesitan su IA personal 24/7</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)
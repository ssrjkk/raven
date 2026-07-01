<div align="center">
  <h1>Raven AI</h1>
  <p><i>엔터프라이즈 개인 AI 비서. 25+ 채널. RavenFlow. RavenCode. 음성. Canvas. Nodes.</i></p>

  <a href="#features">기능</a> •
  <a href="#quickstart">빠른 시작</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">아키텍처</a> •
  <a href="#tech-stack">기술 스택</a> •
  <a href="#license">라이선스</a>

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

## Raven AI를 선택해야 하는 이유

**Raven AI**는 단순한 봇이 아닙니다. 서버에서 24/7 작동하는 완전한 엔터프라이즈급 자동화 AI 어시스턴트입니다.

생각합니다. 계획합니다. 행동합니다.

- **12개 메신저에서 소통** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE + 웹 채팅
- **태스크 실행** — 목표를 단계로 분해, 도구로 각 단계 실행, 결과 반환
- **모니터 실행** — 웹사이트 핑, 가격 확인, RSS, 파일, 프로세스 모니터링 및 알림 전송
- **코드 작성** — 코드베이스 인덱싱, 심볼 검색, 파일 리뷰, 개발 세션 관리
- **예약 루틴** — 아침 브리핑, 이메일 확인, 파일 정리
- **RAG 메모리** — 문서 의미 검색, PDF/코드 청킹, 대화 메모리
- **웹 대시보드** — 모니터링, 태스크 관리, 모니터 및 루틴 관리를 위한 React 패널
- **다중 사용자 + RBAC** — 관리자, 사용자, 뷰어, 역할 기반 액세스 제어

---

## 빠른 시작

`ash
pip install raven-agent
# 또는 개발용: pip install -e .
cp .env.example .env
# .env 편집 — 최소 하나의 LLM API 키 추가
raven onboard   # 대화형 설정 마법사 (LLM, Telegram, 채널)
raven start
`

브라우저에서 열기:
- **http://localhost:18888** — 웹 채팅
- **http://localhost:18888/dashboard** — 대시보드

### Docker

`ash
docker compose up
`

### 웹 대시보드 (개발)

`ash
cd web
npm install
npm run dev    # http://localhost:5173 (:18888로 프록시)
`

---

## 기능

| 기능 | 설명 |
|------|------|
| **25+개 채널** | Telegram (Whisper 음성→텍스트, 인라인 버튼), Discord (슬래시 명령어 + 임베드), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat |
| **태스크 엔진** | 다단계 플래너 — LLM이 목표를 단계로 분해, 도구 선택, 실행, 결과 반환 |
| **모니터 엔진** | 5가지 유형: HTTP(S), 자산 가격, RSS 피드, 파일/디렉토리, 프로세스. 트리거 조건, 알림, 확인 내역 |
| **코딩 어시스턴트** | 코드 인덱싱 (AST 파싱, 8개 언어), 의미 검색, 파일 리뷰 (LLM 기반), 개발 세션 |
| **루틴** | 자동 예약 실행: send_briefing, check_email, organize_files, send_message |
| **RAG 지식 베이스** | 임베딩 엔진 (OpenAI + 로컬), 벡터 저장소, 문서 청킹 (PDF/TXT/코드), 의미 검색 |
| **워크스페이스 스킬** | workspace/skills/의 스킬: 암호화폐, 아침 브리핑, 웹 검색. SKILL.md를 통해 자동 로드 |
| **웹 대시보드** | React 19 + Vite + Tailwind: 대시보드, 채팅, 태스크, 모니터, 루틴, 코드 세션, 설정 |
| **인증 및 RBAC** | 다중 사용자 인증, 4개 역할 (admin/user/viewer/banned), 16개 권한, Bearer 토큰 |
| **엔터프라이즈 인프라** | 서킷 브레이커, HTTP 풀, 속도 제한기, 지수 백오프 재시도, 감사 로그 (20개 이벤트 유형), Prometheus 메트릭, 헬스 체크 |
| **플러그인 시스템** | 10개 플러그인 — browser, code, cron, files, git, memory, api, ocr, process, sessions. 기능 기반 샌드박스 제어 |
| **안전** | DM 페어링, 채널 허용 목록, Fernet 암호화, 속도 제한, 서브프로세스/Docker 샌드박스 |
| **보안 정책** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow 우선순위, workspaceOnly FS, contextVisibility, sanitize_external_content, 보안 감사 CLI |

---

## CLI

`
raven start                    게이트웨이 시작
raven stop                     중지
raven status                   시스템 상태
raven doctor                   진단
raven onboard                  설정 마법사
raven agent --message ...      에이전트에 메시지 보내기
raven pairing list             페어링 요청
raven pairing approve CODE     사용자 확인
raven models list              사용 가능한 모델
raven plugins list             로드된 플러그인
raven history SESSION_ID       메시지 내역
raven db migrate               DB 마이그레이션
raven db backup                DB 백업
raven task list                태스크 목록
raven task run <goal>          태스크 실행
raven task show <id>           태스크 상세
raven task cancel <id>         태스크 취소
raven monitor list             모니터 목록
raven monitor add ...          모니터 추가
raven code index <path>        코드 인덱싱
raven code search <query>      코드 검색
raven code review <file>       파일 리뷰
raven routine list             루틴 목록
raven routine add ...          루틴 추가
raven security audit           보안 감사
raven security audit --deep    심층 감사 (네트워크, 환경, 의존성)
raven security audit --fix     자동 수정
`

## 채팅 명령어

`
/status              봇 상태
/new                 새 대화
/reset               세션 리셋
/compact             기록 압축
/task <goal>         태스크 실행
/monitor list        모니터 목록
/monitor add <type> <target>  모니터 추가
/code index [path]   코드 인덱싱
/code search <query> 코드 검색
/code review <file>  파일 리뷰
/routine list        루틴 목록
/routine add <action> <sched>  루틴 추가
/help                모든 명령어
/pair <code>        사용자 페어링
`

---

## 아키텍처

`mermaid
flowchart TB
    subgraph Clients["클라이언트 및 채널"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Gateway["API 게이트웨이 계층"]
        GW["Gateway (Go)\n:8000"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT Validation"]
    end

    subgraph Services["마이크로서비스"]
        AS["Auth Service (Go)\n:8001 — JWT, SQLite, gRPC"]
        AC["Agent Core (Python)\n:8002 — LLM Router"]
        ME["Monitor Engine (Go)\n:8003 — SQLite, NATS"]
        RS["RAG Service (Python)\n:8004 — Qdrant"]
        TE["Task Engine (Python)\n:8005 — SQLite, Outbox, Saga"]
        CS["Code Service (Python)\n:8006 — Sandbox"]
    end

    subgraph Observability["관측 가능성"]
        OTEL["OTel Collector\n:4317 gRPC / :4318 HTTP"]
        TEMPO["Tempo\nTrace Storage"]
        LOKI["Loki\nLog Aggregation"]
        PROM["Prometheus\n:9090"]
        GRAF["Grafana\n:3000 — Dashboards"]
    end

    subgraph Messaging["메시지 브로커"]
        NATS["NATS / JetStream\n:4222"]
    end

    subgraph Storage["데이터 계층"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store :6333"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM 공급자"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    subgraph AgentSystem["에이전트 시스템"]
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

---


## 연락처

<div align="center">
  <p>
    <b>Raven AI</b> — <a href="https://github.com/ssrjkk">@ssrjkk</a> 개발
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a>
  </p>
  <p>
    아이디어나 버그가 있나요? → <a href="https://github.com/ssrjkk/raven/issues">Issue 열기</a>
  </p>
  <p>
    기여하고 싶나요? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>엔터프라이즈 개인 AI 비서. 25+ 채널. RavenFlow. RavenCode. 음성. Canvas. Nodes.</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

<div align="center">
  <h1>Raven AI</h1>
  <p><i>2-in-1: <b>RavenCode</b> (opencode 대체 — 자율 코딩 에이전트) + <b>RavenFlow</b> (openclaw 대체 — 지속적 워크플로우 게이트웨이). 25+ 채널. 태스크. 모니터. RAG. 음성. 웹 대시보드.</i></p>

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

## 데모

<p align="center">
  <i>📺 Raven의 실제 모습을 보세요 (30초 데모 GIF — 곧 공개)</i>
</p>

```text
$ raven "이 코드베이스를 설명하고 실패한 테스트를 고쳐줘"
🐦 Raven이 프로젝트를 분석하는 중...
   → LSP 강화: 3개 언어 감지
   → 디버그 세션 계획 중...
   → pytest 실행 — 1개 실패 발견
   → test_users.py의 assert 수정 중
   → PR 열림: #42

$ raven
🐦 인터랙티브 REPL — 작업을 입력하거나 /help
  >
```

---

## Raven AI를 선택해야 하는 이유

**Raven AI**는 단순한 봇이 아닙니다. 서버에서 24/7 작동하는 완전한 엔터프라이즈급 자동화 AI 어시스턴트입니다.

생각합니다. 계획합니다. 행동합니다. 말합니다. 흐릅니다.

- **25+ 채널에서 소통** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, 웹 채팅 + 15개 더
- **RavenCode 에이전트** — LSP 자동 강화, 병렬 멀티세션, plan/safe/fast 모드를 갖춘 자율 코딩 에이전트 (`ravencode`), 30+ 도구
- **RavenFlow 게이트웨이** — 멀티에이전트 라우팅, WebSocket 스트리밍, 세션 관리를 갖춘 지속적 워크플로우 데몬 (`ravenflow`)
- **Canvas 시각적 작업 공간** — 터미널이나 브라우저에서 풍부한 컴포넌트 렌더링 (코드, 표, mermaid 다이어그램, 이미지, 알림)
- **Nodes 분산 실행** — 원격 노드에 등록, 등록 해제, 브로드캐스트 및 실행
- **음성 입출력** — 웨이크워드 ("Raven", "Hey Raven"), STT (Whisper/Google/Azure/Vosk), TTS (ElevenLabs/gTTS/system/Edge)
- **태스크 실행** — 단계로 계획을 세우고 각 단계를 도구로 실행하여 결과 반환
- **모니터 실행** — 웹사이트 핑, 가격 확인, RSS, 파일, 프로세스 모니터링 및 알림 전송
- **예약 루틴** — 아침 브리핑, 이메일 확인, 파일 정리
- **RAG 메모리** — 문서 의미 검색, PDF/코드 청킹, 대화 메모리
- **웹 대시보드** — React 19 + Monaco IDE + Tailwind 대시보드
- **다중 사용자 + RBAC** — 관리자, 사용자, 뷰어, 역할 기반 액세스 제어
- **보안 정책** — 5개 샌드박스 프로필 (main, non-main, code-exec, web-browsing, read-only), 세션별 도구 허용/거부

---

## 빠른 시작

```bash
pip install raven-agent
# 또는 개발용: pip install -e .
cp .env.example .env
# .env 편집 — 최소 하나의 LLM API 키 추가
raven onboard   # 대화형 설정 마법사 (LLM, Telegram, 채널)
raven start     # 전체 플랫폼 시작

# 또는 독립 실행 진입점 사용:
ravencode tui   # RavenCode — 인터랙티브 코딩 에이전트
ravenflow       # RavenFlow — 지속적 워크플로우 게이트웨이
```

### 포트

| 포트 | 서비스 | 설명 |
|------|--------|------|
| **18888** | Web UI | 웹 채팅, 대시보드, Monaco IDE, 설정 |
| **18789** | RavenFlow 게이트웨이 | WebSocket 스트리밍을 지원하는 멀티 에이전트 오케스트레이터 데몬 |

브라우저에서 열기:
- **http://localhost:18888** — 웹 채팅
- **http://localhost:18888/dashboard** — 대시보드
- **http://localhost:18888/ide** — Monaco 편집기 (AI 사이드바 포함)

### Docker

```bash
docker compose up
```

### PostgreSQL (선택, SQLite 대체)

Raven은 기본적으로 각 서비스 데이터를 SQLite에 저장합니다. `DATABASE_URL`을 설정하면
(또는 저장소 `db_path`에 `postgresql://` DSN을 전달) 모든 핵심 저장소(태스크, 모니터,
루틴, 인증, 세션, outbox, 분석, persister)에서 PostgreSQL을 사용합니다.

```bash
pip install "raven-agent[postgres]"   # asyncpg 설치

# 로컬 Postgres 시작 (user/password/db = raven)
docker compose -f docker-compose.postgres.yml up -d

# .env에 추가
DATABASE_URL=postgresql://raven:raven@localhost:5432/raven
```

첫 연결 시 마이그레이션이 자동 실행됩니다. SQLite에서 데이터는 마이그레이션되지 않습니다.

### 웹 대시보드 (개발)

```bash
cd web
npm install
npm run dev    # http://localhost:5173 (:18888로 프록시)
```

---

## 비교

| 기능 | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|------|----------|------------------|---------|---------|---------|
| 자체 호스팅 | ✅ 100% | ✅ | ❌ 클라우드 | ❌ 클라우드 | ❌ 클라우드 |
| 25+ 채널 | ✅ | ❌ | ❌ | ✅ 웹 전용 | ❌ |
| LSP 코딩 에이전트 | ✅ | ❌ | ❌ | ❌ | ✅ 기본 |
| 멀티에이전트 오케스트레이션 | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| 음성 + 웨이크워드 | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| 모니터 및 알림 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 예약 루틴 | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG (로컬 우선) | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBAC 다중 사용자 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5개 샌드박스 프로필 | ✅ | ❌ | ❌ | ❌ | ❌ |
| Canvas 작업 공간 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 분산 실행 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 오프라인 모드 | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| 웹 대시보드 | ✅ React + Monaco | ❌ CLI 전용 | ❌ | ✅ | ✅ IDE |
| 오픈소스 | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| 무료 | ✅ | ✅ | ✅ | ❌ $20/월 | ❌ $10/월 |

---

## 기능

| 기능 | 설명 |
|------|------|
| **25+개 채널** | Telegram (Whisper 음성→텍스트, 인라인 버튼), Discord (슬래시 명령어 + 임베드), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat + 15개 더 (Telegram API, Discord API, Slack RTM, WhatsApp Cloud, Matrix CS, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat, Email IMAP, SMS Twilio, Alexa, Google Home, Discord Webhook, Telegram Webhook, Custom Webhook) |
| **RavenFlow 게이트웨이** | 지속적 워크플로우 데몬 (`ravenflow`) — 포트 18789에서 멀티에이전트 라우팅 엔진, 세션 관리, WebSocket 스트리밍, 채널 기반 디스패치, 샌드박스 정책 |
| **RavenCode 에이전트** | 자율 코딩 에이전트 (`ravencode`) — 인터랙티브 REPL, 스트리밍 응답, 인라인 도구 호출, LSP 강화. 명령어: `/multisession`, `/plan`, `/safe`, `/fast`, `/enrich`, `/exit` |
| **LSP 자동 강화** | `enrich_context()` 프로젝트 스캔, 언어 감지, LSP 서버 시작 (pyright, typescript-language-server, gopls, rust-analyzer), 문서 심볼 수집 |
| **병렬 멀티세션** | `SessionManager` — 동시 `ManagedSession` 태스크, abort/cleanup, 싱글턴 패턴 |
| **Canvas 시각적 작업 공간** | 풍부한 컴포넌트 렌더링: 텍스트, 코드 블록, 표, mermaid 다이어그램, 링크, 이미지, 목록, 알림. 터미널 또는 브라우저 HTML 출력 |
| **Nodes 분산 실행** | 원격 노드 등록/해제, 노드 간 태스크 실행, 모든 등록된 엔드포인트로 브로드캐스트 |
| **음성 입출력** | 웨이크워드 ("Raven", "Hey Raven", "OK Raven"), STT (Whisper, Google, Azure, Vosk), TTS (ElevenLabs, gTTS, 시스템 SAPI, Edge), 마이크 녹음 |
| **샌드박스 보안 정책** | 5개 정책 (main, non-main, code-exec, web-browsing, read-only) — 도구 허용/거부, 네트워크 제어, 리소스 제한. 런타임 변경 가능 |
| **Cron / 스케줄링** | `cron_schedule`/`cron_list`/`cron_cancel` 도구로 반복 태스크 스케줄링 (APScheduler 기반) |
| **통합 런처** | `main.py` — 모든 서비스 시작 (Raven, RavenFlow, Web UI) + graceful shutdown |
| **태스크 엔진** | 다단계 플래너 — LLM이 목표를 단계로 분해, 도구 선택, 실행, 결과 반환 |
| **모니터 엔진** | 5가지 유형: HTTP(S), 자산 가격, RSS 피드, 파일/디렉토리, 프로세스. 트리거 조건, 알림, 확인 내역 |
| **루틴** | 자동 예약 실행: send_briefing, check_email, organize_files, send_message |
| **RAG 지식 베이스** | 임베딩 엔진 (OpenAI + 로컬), 벡터 저장소, 문서 청킹 (PDF/TXT/코드), 의미 검색 |
| **워크스페이스 스킬** | `workspace/skills/`의 스킬: 암호화폐, 아침 브리핑, 웹 검색. SKILL.md를 통해 자동 로드 |
| **웹 대시보드 + IDE** | React 19 + Vite + Tailwind + Monaco Editor: 대시보드, 채팅, 태스크, 모니터, 루틴, 코드 세션, 설정, IDE (에디터 + 터미널 + AI 사이드바) |
| **인증 및 RBAC** | 다중 사용자 인증, 4개 역할 (admin/user/viewer/banned), 16개 권한, Bearer 토큰 |
| **엔터프라이즈 인프라** | 서킷 브레이커, HTTP 풀, 속도 제한기, 지수 백오프 재시도, 감사 로그 (20개 이벤트 유형), Prometheus 메트릭, 헬스 체크 |
| **플러그인 시스템** | 10개 플러그인 — browser, code, cron, files, git, memory, api, ocr, process, sessions. 기능 기반 샌드박스 제어 |
| **안전** | DM 페어링, 채널 허용 목록, Fernet 암호화, 속도 제한, 서브프로세스/Docker 샌드박스 |
| **보안 정책** | ToolPolicyEvaluator, exec.security (deny/ask/full), deny > allow 우선순위, workspaceOnly FS, contextVisibility, sanitize_external_content, 보안 감사 CLI |

---

## CLI

```
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
raven code                     인터랙티브 코딩 REPL
raven code --project <dir>     프로젝트 디렉토리에서 REPL 시작
raven code --plan              플랜 전용 모드 (쓰기 없음)
raven code --safe              안전 모드 (쓰기 전 확인)
raven code --parallel          병렬 멀티세션 활성화
raven code index <path>        코드 인덱싱
raven code search <query>      코드 검색
raven code review <file>       파일 리뷰
raven routine list             루틴 목록
raven routine add ...          루틴 추가
raven security audit           보안 감사
raven security audit --deep    심층 감사 (네트워크, 환경, 의존성)
raven security audit --fix     자동 수정
raven flow serve --port 18789  RavenFlow 게이트웨이 데몬 시작
raven flow ask <message>       실행 중인 게이트웨이에 메시지 보내기
raven flow sessions            활성 Flow 세션 목록

ravencode tui                  인터랙티브 TUI
ravencode serve                헤드리스 HTTP 서버
ravencode web                  웹 인터페이스
ravencode session list         저장된 세션 목록
ravencode auth login           API 키 구성

ravenflow --port 18789         RavenFlow 게이트웨이 데몬 시작
ravenflow serve --port 18789   RavenFlow 게이트웨이 데몬 시작
```

## 채팅 명령어

```
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
/pair <code>         사용자 페어링
```

---

## 아키텍처

```mermaid
flowchart TB
    subgraph Clients["클라이언트 및 채널"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["코어 시스템"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["관측 가능성"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["데이터 계층"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM 공급자"]
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

## 프로젝트 구조

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

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| **백엔드** | Python 3.11+, FastAPI, asyncio, SQLite (기본) + PostgreSQL (선택) |
| **LLM** | Ollama (로컬) → OpenRouter → Anthropic → OpenAI (장애 조치) |
| **메모리** | SQLite / PostgreSQL + ChromaDB + numpy 벡터 저장소 |
| **RAG** | Qdrant 벡터 저장소, 인메모리 폴백, n-gram 임베딩 |
| **인증** | bcrypt, JWT (HS256), RBAC (4개 역할, 16개 권한) |
| **프론트엔드** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **채널** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI 데몬 (포트 18789), 라우팅 엔진, WebSocket 스트리밍, 멀티에이전트 디스패치 |
| **RavenCode** | 인터랙티브 REPL, LSP 자동 강화 (pyright/tsserver/gopls/rust-analyzer), 병렬 멀티세션, plan/safe/fast 모드, 30+ 도구 |
| **Canvas** | 풍부한 컴포넌트 렌더링 (코드, 표, mermaid, 이미지, 링크, 목록, 알림), HTML + 브라우저 출력 |
| **Nodes** | 분산 노드 레지스트리, 브로드캐스트 실행, 비동기 HTTP 디스패치 |
| **음성** | WakeWordDetector (speech_recognition), Whisper/Google/Azure/Vosk STT, ElevenLabs/gTTS/SAPI/Edge TTS |
| **샌드박스 정책** | 5개 정책 프로필 (main/non-main/code-exec/web-browsing/read-only), 런타임 도구 허용/거부 |
| **메시지 브로커** | NATS + JetStream (선택, 분산 모드) |
| **복원력** | 서킷 브레이커, 속도 제한기, 지수 백오프 재시도, 감사 로그 (20개 이벤트 유형), Prometheus 메트릭, 헬스 체크 |
| **관측 가능성** | OpenTelemetry (트레이스 + 메트릭), health/ready 프로브 |
| **보안** | 속도 제한, JWT 인증, DM 페어링, Fernet 암호화, RBAC, 플러그인 샌드박스, ToolPolicyEvaluator (deny/allow), exec 보안 정책 (deny/ask/full), contextVisibility, 작업 공간 격리, 보안 감사 CLI |
| **CI/CD** | GitHub Actions — 병렬 lint + typecheck + test, Allure 보고, Codecov |
| **배포** | Docker, docker-compose, systemd |
| **테스트** | pytest (4593+ 테스트, Allure 보고), Vitest (React) |

---

## RavenCode — 터미널 코딩 에이전트

Raven AI는 `raven code` — 완전한 기능을 갖춘 인터랙티브 터미널 코딩 에이전트를 포함합니다:

```bash
# REPL 시작
raven code --project ./my-project

# REPL에서:
raven@project> FastAPI로 REST API 만들기
# ... 응답 스트리밍, 도구 호출, 인라인 파일 편집

# 내장 명령어:
/help          사용 가능한 명령어 표시
/multisession  하위 작업을 병렬로 실행
/plan          플랜 전용 모드 전환 (쓰기 없음)
/safe          안전 모드 전환 (쓰기 전 확인)
/fast          빠른 모드 전환 (강화 건너뛰기)
/enrich        LSP 분석 새로 고침
/session <id>  병렬 세션으로 전환
/exit          종료
```

### RavenFlow 게이트웨이

WebSocket 스트리밍을 지원하는 멀티에이전트 오케스트레이터 데몬:

```bash
# 게이트웨이 시작 (독립 명령어)
ravenflow --port 18789

# 또는 메인 CLI를 통해
raven flow serve --port 18789

# 에이전트에 메시지 보내기
raven flow ask "README 요약해줘"

# 활성 세션 목록
raven flow sessions
```

### Canvas 시각적 작업 공간

에이전트에서 직접 풍부한 시각적 컴포넌트를 렌더링합니다:

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### 통합 런처

단일 `main.py` 런처가 모든 서비스를 시작합니다:
```bash
python main.py --web-port 5173 --flow-port 18789
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
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    아이디어나 버그가 있나요? → <a href="https://github.com/ssrjkk/raven/issues">Issue 열기</a>
  </p>
  <p>
    기여하고 싶나요? → <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>24/7 개인 AI가 필요한 개발자를 위해 만들어졌습니다</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)
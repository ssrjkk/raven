<div align="center">
  <h1>Raven AI</h1>
  <p><i>엔터프라이즈급 개인 AI 어시스턴트. 12개 채널. 태스크 엔진. 모니터. 코딩 어시스턴트. RAG 지식 베이스. 웹 대시보드.</i></p>

  <a href="#features">기능</a> •
  <a href="#quickstart">빠른 시작</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">아키텍처</a> •
  <a href="#tech-stack">기술 스택</a> •
  <a href="#license">라이선스</a>

  [![CI](https://img.shields.io/github/actions/workflow/status/ssrjkk/raven/ci.yml?branch=main&label=CI&logo=github)]()
  [![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white)]()
  [![License](https://img.shields.io/badge/license-MIT-green)]()
  [![Channels](https://img.shields.io/badge/channels-12-8A2BE2)]()
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
| **12개 채널** | Telegram (Whisper 음성→텍스트, 인라인 버튼), Discord (슬래시 명령어 + 임베드), Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, WebChat |
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

## 프로젝트 트리

`
raven/
├── raven/                      # 메인 Python 패키지
│   ├── agent/                  ReAct 에이전트, 멀티 에이전트 레지스트리, 워크스페이스 프롬프트
│   ├── gateway/                메시지 라우팅, 세션, 명령어
│   ├── core/
│   │   ├── auth/               인증, RBAC (4개 역할, 16개 권한), API 토큰
│   │   ├── security/           ToolPolicyEvaluator, PII 편집, SecurityAudit
│   │   ├── task_engine/        플래너, 실행기, 태스크 저장소
│   │   ├── monitor/            HTTP, 가격, RSS, 파일, 프로세스 모니터 + 조건
│   │   ├── rag/                임베딩 엔진, 청킹, 벡터 저장소
│   │   ├── llm.py              LLM 공급자 (OpenAI, Anthropic, Ollama, OpenRouter) + 장애 조치
│   │   ├── config.py           Pydantic 설정 + YAML 설정
│   │   └── admin_api.py        관리자 REST API
│   ├── channels/               12개 채널, 메시지 버스, CircuitBreakerChannel
│   ├── cli/                    CLI (click + rich)
│   ├── tools/                  플러그인 도구
│   ├── tui/                    터미널 UI (textual)
│   └── workspace/              워크스페이스 관리자, 스킬, 플러그인 로더
├── services/                   # 마이크로서비스 (Go + Python)
│   ├── gateway/                Go 게이트웨이 (auth proxy, circuit breaker, rate limiter, 메트릭, gRPC)
│   ├── auth/                   Go 인증 서비스 (SQLite, JWT, gRPC, Redis rate limiter)
│   ├── agent-core/             Python — LLM 라우터 (Ollama/OpenAI/Anthropic), NATS pub/sub
│   ├── monitor-engine/         Go 모니터 서비스 (SQLite, NATS, Prometheus)
│   ├── rag-service/            Python — 의미 검색 (Qdrant + 인메모리 폴백)
│   ├── task-engine/            Python — 태스크 플래너 (SQLite, NATS, 멱등성, outbox, saga)
│   ├── code-service/           Python — 코드 샌드박스 (subprocess, NATS)
│   └── proto/                  Protobuf 정의 + 생성된 Go 코드
├── web/                        React 19 + Vite + Tailwind 대시보드
├── deploy/                     Docker, k8s, systemd, 관측 가능성 스택
├── daemon/                     Rust 데몬 (ravend): 시스템 메트릭, 프로세스 관리
├── aios/                       AI-OS-MVP 에이전트 프레임워크
└── plugins/                    사용자 플러그인
`

## 기술 스택

| 계층 | 기술 |
|------|------|
| **백엔드** | Python 3.13+, FastAPI, asyncio, SQLite (modernc.org/sqlite) |
| **LLM** | Ollama (로컬) → OpenRouter → Anthropic → OpenAI (장애 조치) |
| **메모리** | SQLite + ChromaDB + numpy 벡터 저장소 |
| **RAG** | Qdrant 벡터 저장소, 인메모리 폴백, n-gram 임베딩 |
| **인증** | bcrypt, JWT (HS256), gRPC, RBAC (4개 역할, 16개 권한) |
| **프론트엔드** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **채널** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio |
| **메시지 브로커** | NATS + JetStream (스트림: agent.response, monitor.check.completed, task.events, auth.user.created) |
| **게이트웨이** | Go 1.26 — circuit breaker, rate limiter, auth proxy, gRPC retry, OpenTelemetry |
| **인증 서비스** | Go 1.26 — SQLite, JWT, gRPC, token bucket rate limiter, OpenTelemetry |
| **모니터 엔진** | Go 1.26 — HTTP 헬스 체크, SQLite, NATS 이벤트, Prometheus 메트릭 |
| **복원력** | Circuit breaker, gRPC retry (지수 백오프), rate limiter, outbox 패턴, saga 패턴, 멱등성 |
| **관측 가능성** | OpenTelemetry (트레이스 + 메트릭), Prometheus, Grafana (12개 패널), Loki, Tempo, health/ready 프로브 |
| **보안** | 속도 제한, JWT 인증, DM 페어링, Fernet 암호화, RBAC, 플러그인 샌드박스, ToolPolicyEvaluator (deny/allow), exec 보안 정책 (deny/ask/full), contextVisibility, 워크스페이스 격리, 보안 감사 CLI |
| **CI/CD** | GitHub Actions — 병렬 Go/Python/web lint+test+build, Allure TestOps, Docker buildx, Codecov, Playwright E2E, k6 부하 테스트 |
| **배포** | Docker (다단계, distroless, non-root), docker-compose (마이크로서비스 스택), Kubernetes 매니페스트, systemd, launchd |
| **테스트** | pytest (800+ 테스트, Allure 보고), Go 테이블 기반 테스트, Vitest (React), Playwright (E2E), k6 (부하) |

---

## AI-OS-MVP — 하이브리드 아키텍처

Raven AI는 이제 하이브리드 **AI-OS-MVP** 아키텍처로 작동합니다:

`
raven-ai/
├── aios/                       # AI-OS-MVP 브리지 (Python)
│   ├── api/bridge.py           # AI Gateway 엔드포인트
│   ├── agents/orchestrator.py  # 에이전트 오케스트레이터
│   └── runtime/adapter.py      # 통합 런타임
├── web/                        # Web IDE (React 19)
│   └── src/pages/IDE.tsx       # 편집기 + 터미널 IDE
├── desktop-tauri/              # Tauri 데스크톱 (Rust)
├── packages/                   # TypeScript 패키지
│   ├── ai-core/                # AI 라우터 + 공급자
│   ├── agents/                 # 멀티 에이전트 시스템
│   ├── runtime/                # 터미널, fs, docker
│   └── repo/                   # 인덱서, AST, 임베딩
`

### AI-OS-MVP 빠른 시작

`ash
# AI Gateway (Raven 위의 브리지)
raven aios gateway --port 3001

# 자율 에이전트 실행
raven aios run "REST API 생성" --agent autonomous

# 명령어 실행
raven aios exec "npm run dev"

# Web IDE (Monaco 편집기)
cd web && npm install && npm run dev
# http://localhost:5173/ide 열기
`

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
  <p><i>24/7 개인 AI가 필요한 개발자를 위해</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

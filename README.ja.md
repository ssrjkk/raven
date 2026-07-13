<div align="center">
  <h1>Raven AI</h1>
  <p><i>2-in-1: <b>Ravencode</b> (opencode代替 — 自律コーディングエージェント) + <b>RavenFlow</b> (openclaw代替 — 永続ワークフローゲートウェイ). 25+チャンネル. タスク. モニター. RAG. 音声. Webダッシュボード.</i></p>

  <a href="#features">機能</a> •
  <a href="#quickstart">クイックスタート</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">アーキテクチャ</a> •
  <a href="#tech-stack">技術スタック</a> •
  <a href="#license">ライセンス</a>

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
  [![Hybrid](https://img.shields.io/badge/2--in--1-ravencode+%2B+ravenflow-orange)]()

  [English](README.md) •
  [Русский](README.ru.md) •
  [简体中文](README.zh.md) •
  [한국어](README.ko.md) •
  [Español](README.es.md) •
  [日本語](README.ja.md) •
</div>

---

## Raven AIを選ぶ理由

**Raven AI**は単なるボットではありません。サーバー上で24時間365日稼働する、本格的なエンタープライズ向け自動AIアシスタントです。

考えます。計画します。行動します。

- **12のメッセンジャーで通信** — Telegram、Discord、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE + Webチャット
- **タスクを実行** — 目標をステップに分解し、ツールで実行、結果を返す
- **モニターを実行** — Webサイトのping、価格チェック、RSS、ファイル、プロセスを監視しアラート送信
- **コードを記述** — コードベースのインデックス化、シンボル検索、ファイルレビュー、開発セッション管理
- **スケジュールルーティン** — 朝のブリーフィング、メールチェック、ファイル整理
- **RAGメモリ** — 文書のセマンティック検索、PDF/コードのチャンキング、会話メモリ
- **Webダッシュボード** — モニタリング、タスク管理、モニター、ルーティン管理のReactパネル
- **マルチユーザー + RBAC** — 管理者、ユーザー、ビューアー、ロールベースのアクセス制御

---

## クイックスタート

`ash
pip install raven-agent
# 開発用: pip install -e .
cp .env.example .env
# .envを編集 — 少なくとも1つのLLM APIキーを追加
raven onboard   # インタラクティブセットアップウィザード（LLM、Telegram、チャンネル）
raven start
`

### ポート

| ポート | サービス | 説明 |
|--------|----------|------|
| **18888** | Web UI | Webチャット、ダッシュボード、Monaco IDE、設定 |
| **18789** | RavenFlow ゲートウェイ | WebSocketストリーミング対応マルチエージェントオーケストレータデーモン |

ブラウザで開く:
- **http://localhost:18888** — Webチャット
- **http://localhost:18888/dashboard** — ダッシュボード
- **http://localhost:18888/ide** — Monacoエディタ（AIサイドバー付き）

### Docker

`ash
docker compose up
`

### Webダッシュボード（開発）

`ash
cd web
npm install
npm run dev    # http://localhost:5173（:18888へのプロキシ）
`

---

## 機能

| 機能 | 説明 |
|------|------|
| **25+チャンネル** | Telegram（Whisperによる音声→テキスト、インラインボタン）、Discord（スラッシュコマンド+埋め込み）、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat |
| **タスクエンジン** | マルチステッププランナー — LLMが目標を分解、ツール選択、実行、結果返却 |
| **モニターエンジン** | 5タイプ: HTTP(S)、資産価格、RSSフィード、ファイル/ディレクトリ、プロセス。トリガー条件、アラート、チェック履歴 |
| **コーディングアシスタント** | コードインデックス（AST解析、8言語）、セマンティック検索、ファイルレビュー（LLM駆動）、開発セッション |
| **ルーティン** | 自動スケジュール実行: send_briefing、check_email、organize_files、send_message |
| **RAG知識ベース** | 埋め込みエンジン（OpenAI + ローカル）、ベクトルストア、ドキュメントチャンキング（PDF/TXT/コード）、セマンティック検索 |
| **ワークスペーススキル** | workspace/skills/内のスキル: 暗号通貨、朝のブリーフィング、Web検索。SKILL.mdから自動読み込み |
| **Webダッシュボード** | React 19 + Vite + Tailwind: ダッシュボード、チャット、タスク、モニター、ルーティン、コードセッション、設定 |
| **認証とRBAC** | マルチユーザー認証、4ロール（admin/user/viewer/banned）、16権限、Bearerトークン |
| **エンタープライズ基盤** | サーキットブレーカー、HTTPプール、レートリミッター、指数バックオフリトライ、監査ログ（20イベントタイプ）、Prometheusメトリクス、ヘルスチェック |
| **プラグインシステム** | 10プラグイン — browser、code、cron、files、git、memory、api、ocr、process、sessions。ケイパビリティベースのサンドボックス制御 |
| **安全性** | DMペアリング、チャンネル許可リスト、Fernet暗号化、レート制限、サブプロセス/Dockerサンドボックス |
| **セキュリティポリシー** | ToolPolicyEvaluator、exec.security（deny/ask/full）、deny > allow優先度、workspaceOnly FS、contextVisibility、sanitize_external_content、セキュリティ監査CLI |

---

## CLI

`
raven start                    ゲートウェイ起動
raven stop                     停止
raven status                   システム状態
raven doctor                   診断
raven onboard                  セットアップウィザード
raven agent --message ...      エージェントにメッセージ送信
raven pairing list             ペアリングリクエスト
raven pairing approve CODE     ユーザー確認
raven models list              利用可能なモデル
raven plugins list             ロード済みプラグイン
raven history SESSION_ID       メッセージ履歴
raven db migrate               DBマイグレーション
raven db backup                DBバックアップ
raven task list                タスク一覧
raven task run <goal>          タスク実行
raven task show <id>           タスク詳細
raven task cancel <id>         タスクキャンセル
raven monitor list             モニター一覧
raven monitor add ...          モニター追加
raven code index <path>        コードインデックス
raven code search <query>      コード検索
raven code review <file>       ファイルレビュー
raven routine list             ルーティン一覧
raven routine add ...          ルーティン追加
raven security audit           セキュリティ監査
raven security audit --deep    詳細監査（ネットワーク、環境、依存関係）
raven security audit --fix     自動修正
`

## チャットコマンド

`
/status              ボット状態
/new                 新規会話
/reset               セッションリセット
/compact             履歴圧縮
/task <goal>         タスク実行
/monitor list        モニター一覧
/monitor add <type> <target>  モニター追加
/code index [path]   コードインデックス
/code search <query> コード検索
/code review <file>  ファイルレビュー
/routine list        ルーティン一覧
/routine add <action> <sched>  ルーティン追加
/help                全コマンド
/pair <code>        ユーザーペアリング
`

---

## アーキテクチャ

`mermaid
flowchart TB
    subgraph Clients["クライアントとチャンネル"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["コアシステム"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["可観測性"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["データ層"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLMプロバイダー"]
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



## お問い合わせ

<div align="center">
  <p>
    <b>Raven AI</b> — <a href="https://github.com/ssrjkk">@ssrjkk</a> によって開発
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a>
  </p>
  <p>
    アイデアやバグがありますか？→ <a href="https://github.com/ssrjkk/raven/issues">Issueを開く</a>
  </p>
  <p>
    貢献したいですか？→ <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>2-in-1: RavenCode + RavenFlow. 25+チャンネル. タスク. モニター. RAG. 音声. Webダッシュボード.</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

<div align="center">
  <h1>Raven AI</h1>
  <p><i>エンタープライズグレードのパーソナルAIアシスタント。12チャンネル。タスクエンジン。モニター。コーディングアシスタント。RAG知識ベース。Webダッシュボード。</i></p>

  <a href="#features">機能</a> •
  <a href="#quickstart">クイックスタート</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">アーキテクチャ</a> •
  <a href="#tech-stack">技術スタック</a> •
  <a href="#license">ライセンス</a>

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

ブラウザで開く:
- **http://localhost:18888** — Webチャット
- **http://localhost:18888/dashboard** — ダッシュボード

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
| **12チャンネル** | Telegram（Whisperによる音声→テキスト、インラインボタン）、Discord（スラッシュコマンド+埋め込み）、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat |
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

    subgraph Gateway["APIゲートウェイ層"]
        GW["Gateway (Go)\n:8000"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT Validation"]
    end

    subgraph Services["マイクロサービス"]
        AS["Auth Service (Go)\n:8001 — JWT, SQLite, gRPC"]
        AC["Agent Core (Python)\n:8002 — LLM Router"]
        ME["Monitor Engine (Go)\n:8003 — SQLite, NATS"]
        RS["RAG Service (Python)\n:8004 — Qdrant"]
        TE["Task Engine (Python)\n:8005 — SQLite, Outbox, Saga"]
        CS["Code Service (Python)\n:8006 — Sandbox"]
    end

    subgraph Observability["可観測性"]
        OTEL["OTel Collector\n:4317 gRPC / :4318 HTTP"]
        TEMPO["Tempo\nTrace Storage"]
        LOKI["Loki\nLog Aggregation"]
        PROM["Prometheus\n:9090"]
        GRAF["Grafana\n:3000 — Dashboards"]
    end

    subgraph Messaging["メッセージブローカー"]
        NATS["NATS / JetStream\n:4222"]
    end

    subgraph Storage["データ層"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store :6333"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLMプロバイダー"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    subgraph AgentSystem["エージェントシステム"]
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

## プロジェクトツリー

`
raven/
├── raven/                      # メインPythonパッケージ
│   ├── agent/                  ReActエージェント、マルチエージェント登録、ワークスペースプロンプト
│   ├── gateway/                メッセージルーティング、セッション、コマンド
│   ├── core/
│   │   ├── auth/               認証、RBAC（4ロール、16権限）、APIトークン
│   │   ├── security/           ToolPolicyEvaluator、PII編集、SecurityAudit
│   │   ├── task_engine/        プランナー、実行器、タスクストレージ
│   │   ├── monitor/            HTTP、価格、RSS、ファイル、プロセスモニター＋条件
│   │   ├── rag/                埋め込みエンジン、チャンキング、ベクトルストア
│   │   ├── llm.py              LLMプロバイダー（OpenAI、Anthropic、Ollama、OpenRouter）+フェイルオーバー
│   │   ├── config.py           Pydantic設定+YAML設定
│   │   └── admin_api.py        管理者REST API
│   ├── channels/               12チャンネル、メッセージバス、CircuitBreakerChannel
│   ├── cli/                    CLI（click + rich）
│   ├── tools/                  プラグインツール
│   ├── tui/                    ターミナルUI（textual）
│   └── workspace/              ワークスペースマネージャー、スキル、プラグインローダー
├── services/                   # マイクロサービス（Go + Python）
│   ├── gateway/                Goゲートウェイ（auth proxy、circuit breaker、rate limiter、メトリクス、gRPC）
│   ├── auth/                   Go認証サービス（SQLite、JWT、gRPC、Redis rate limiter）
│   ├── agent-core/             Python — LLMルーター（Ollama/OpenAI/Anthropic）、NATS pub/sub
│   ├── monitor-engine/         Goモニターサービス（SQLite、NATS、Prometheus）
│   ├── rag-service/            Python — セマンティック検索（Qdrant + インメモリフォールバック）
│   ├── task-engine/            Python — タスクプランナー（SQLite、NATS、冪等性、outbox、saga）
│   ├── code-service/           Python — コードサンドボックス（subprocess、NATS）
│   └── proto/                  Protobuf定義+生成Goコード
├── web/                        React 19 + Vite + Tailwindダッシュボード
├── deploy/                     Docker、k8s、systemd、可観測性スタック
├── daemon/                     Rustデーモン（ravend）：システムメトリクス、プロセス管理
├── aios/                       AI-OS-MVPエージェントフレームワーク
└── plugins/                    ユーザープラグイン
`

## 技術スタック

| 層 | 技術 |
|----|------|
| **バックエンド** | Python 3.13+, FastAPI, asyncio, SQLite (modernc.org/sqlite) |
| **LLM** | Ollama（ローカル）→ OpenRouter → Anthropic → OpenAI（フェイルオーバー） |
| **メモリ** | SQLite + ChromaDB + numpyベクトルストア |
| **RAG** | Qdrantベクトルストア、インメモリフォールバック、n-gram埋め込み |
| **認証** | bcrypt、JWT（HS256）、gRPC、RBAC（4ロール、16権限） |
| **フロントエンド** | React 19、Vite 6、Tailwind CSS 4、react-router-dom、Monaco Editor |
| **チャンネル** | python-telegram-bot、discord.py、slack-sdk、matrix-nio、IRC asyncio |
| **メッセージブローカー** | NATS + JetStream（ストリーム: agent.response、monitor.check.completed、task.events、auth.user.created） |
| **ゲートウェイ** | Go 1.26 — circuit breaker、rate limiter、auth proxy、gRPC retry、OpenTelemetry |
| **認証サービス** | Go 1.26 — SQLite、JWT、gRPC、token bucket rate limiter、OpenTelemetry |
| **モニターエンジン** | Go 1.26 — HTTPヘルスチェック、SQLite、NATSイベント、Prometheusメトリクス |
| **回復力** | Circuit breaker、gRPC retry（指数バックオフ）、rate limiter、outboxパターン、sagaパターン、冪等性 |
| **可観測性** | OpenTelemetry（トレース+メトリクス）、Prometheus、Grafana（12パネル）、Loki、Tempo、health/readyプローブ |
| **セキュリティ** | レート制限、JWT認証、DMペアリング、Fernet暗号化、RBAC、プラグインサンドボックス、ToolPolicyEvaluator（deny/allow）、execセキュリティポリシー（deny/ask/full）、contextVisibility、ワークスペース分離、セキュリティ監査CLI |
| **CI/CD** | GitHub Actions — 並列Go/Python/web lint+test+build、Allure TestOps、Docker buildx、Codecov、Playwright E2E、k6負荷テスト |
| **デプロイ** | Docker（マルチステージ、distroless、non-root）、docker-compose（マイクロサービススタック）、Kubernetesマニフェスト、systemd、launchd |
| **テスト** | pytest（800+テスト、Allureレポート）、Goテーブル駆動テスト、Vitest（React）、Playwright（E2E）、k6（負荷） |

---

## AI-OS-MVP — ハイブリッドアーキテクチャ

Raven AIは現在、ハイブリッド**AI-OS-MVP**アーキテクチャで動作しています:

`
raven-ai/
├── aios/                       # AI-OS-MVPブリッジ（Python）
│   ├── api/bridge.py           # AI Gatewayエンドポイント
│   ├── agents/orchestrator.py  # エージェントオーケストレーター
│   └── runtime/adapter.py      # 統合ランタイム
├── web/                        # Web IDE（React 19）
│   └── src/pages/IDE.tsx       # エディター+ターミナル付きIDE
├── desktop-tauri/              # Tauriデスクトップ（Rust）
├── packages/                   # TypeScriptパッケージ
│   ├── ai-core/                # AIルーター+プロバイダー
│   ├── agents/                 # マルチエージェントシステム
│   ├── runtime/                # ターミナル、fs、docker
│   └── repo/                   # インデクサー、AST、埋め込み
`

### AI-OS-MVP クイックスタート

`ash
# AI Gateway（Raven上のブリッジ）
raven aios gateway --port 3001

# 自律エージェントを実行
raven aios run "REST APIを作成" --agent autonomous

# コマンドを実行
raven aios exec "npm run dev"

# Web IDE（Monacoエディター）
cd web && npm install && npm run dev
# http://localhost:5173/ide を開く
`

---

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
  <p><i>24時間365日パーソナルAIを必要とする開発者のために</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

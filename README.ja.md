<div align="center">
  <h1>Raven AI</h1>
  <p><i>2-in-1: <b>RavenCode</b> (opencode代替 — 自律コーディングエージェント) + <b>RavenFlow</b> (openclaw代替 — 永続ワークフローゲートウェイ). 25+チャンネル. タスク. モニター. RAG. 音声. Webダッシュボード.</i></p>

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

## デモ

<p align="center">
  <i>📺 Ravenの動作を見る（30秒デモGIF — 近日公開）</i>
</p>

```text
$ raven "このコードベースを説明して、失敗しているテストを修正して"
🐦 Ravenがプロジェクトを分析中...
   → LSP拡張: 3言語を検出
   → デバッグセッションを計画中...
   → pytest実行 — 1つの失敗を発見
   → test_users.pyのアサーションを修正中
   → PRをオープン: #42

$ raven
🐦 インタラクティブREPL — タスクを入力するか/help
  >
```

---

## Raven AIを選ぶ理由

**Raven AI**は単なるボットではありません。サーバー上で24時間365日稼働する、本格的なエンタープライズ向け自動AIアシスタントです。

考えます。計画します。行動します。話します。流れます。

- **25+のチャンネルで通信** — Telegram、Discord、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、Webチャット + さらに15
- **RavenCodeエージェント** — LSP自動拡張、並列マルチセッション、plan/safe/fastモードを備えた自律コーディングエージェント（`ravencode`）、30+ツール
- **RavenFlowゲートウェイ** — マルチエージェントルーティング、WebSocketストリーミング、セッション管理を備えた永続ワークフローデーモン（`ravenflow`）
- **Canvasビジュアルワークスペース** — ターミナルまたはブラウザでリッチコンポーネントをレンダリング（コード、表、mermaid図、画像、アラート）
- **Nodes分散実行** — リモートノードに登録・解除・ブロードキャスト・実行
- **音声入出力** — ウェイクワード（"Raven"、"Hey Raven"）、STT（Whisper/Google/Azure/Vosk）、TTS（ElevenLabs/gTTS/system/Edge）
- **タスクを実行** — ステップの計画を構築し、各ステップをツールで実行して結果を返す
- **モニターを実行** — Webサイトのping、価格チェック、RSS、ファイル、プロセスを監視しアラート送信
- **スケジュールルーティン** — 朝のブリーフィング、メールチェック、ファイル整理
- **RAGメモリ** — 文書のセマンティック検索、PDF/コードのチャンキング、会話メモリ
- **Webダッシュボード** — React 19 + Monaco IDE + Tailwind
- **マルチユーザー + RBAC** — 管理者、ユーザー、ビューアー、ロールベースのアクセス制御
- **セキュリティポリシー** — 5つのサンドボックスプロファイル（main、non-main、code-exec、web-browsing、read-only）、セッションごとのツール許可/拒否

---

## クイックスタート

```bash
pip install raven-agent
# 開発用: pip install -e .
cp .env.example .env
# .envを編集 — 少なくとも1つのLLM APIキーを追加
raven onboard   # インタラクティブセットアップウィザード（LLM、Telegram、チャンネル）
raven start     # フルプラットフォームを起動

# または単独のエントリーポイントを使用:
ravencode tui   # RavenCode — インタラクティブコーディングエージェント
ravenflow       # RavenFlow — 永続ワークフローゲートウェイ
```

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

```bash
docker compose up
```

### PostgreSQL（オプション、SQLiteを置き換え）

Ravenはデフォルトで各サービスのデータをSQLiteに保存します。`DATABASE_URL`を設定するか
（ストアの `db_path` に `postgresql://` DSNを渡す）、すべての主要ストア（タスク、モニター、
ルーティン、認証、セッション、outbox、分析、persister）でPostgreSQLを使用できます。

```bash
pip install "raven-agent[postgres]"   # asyncpgをインストール

# ローカルPostgresを起動（user/password/db = raven）
docker compose -f docker-compose.postgres.yml up -d

# .envに追加
DATABASE_URL=postgresql://raven:raven@localhost:5432/raven
```

初回接続時にマイグレーションが自動実行されます。SQLiteからのデータ移行はありません。

### Webダッシュボード（開発）

```bash
cd web
npm install
npm run dev    # http://localhost:5173（:18888へのプロキシ）
```

---

## 比較

| 機能 | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|------|----------|------------------|---------|---------|---------|
| セルフホスト | ✅ 100% | ✅ | ❌ クラウド | ❌ クラウド | ❌ クラウド |
| 25+チャンネル | ✅ | ❌ | ❌ | ✅ Webのみ | ❌ |
| LSP対応コーディングエージェント | ✅ | ❌ | ❌ | ❌ | ✅ 基本 |
| マルチエージェントオーケストレーション | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| 音声 + ウェイクワード | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| モニターとアラート | ✅ | ❌ | ❌ | ❌ | ❌ |
| スケジュールルーティン | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG（ローカルファースト） | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBACマルチユーザー | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5つのサンドボックスプロファイル | ✅ | ❌ | ❌ | ❌ | ❌ |
| Canvasワークスペース | ✅ | ❌ | ❌ | ❌ | ❌ |
| 分散実行 | ✅ | ❌ | ❌ | ❌ | ❌ |
| オフラインモード | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| Webダッシュボード | ✅ React + Monaco | ❌ CLIのみ | ❌ | ✅ | ✅ IDE |
| オープンソース | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| 無料 | ✅ | ✅ | ✅ | ❌ $20/月 | ❌ $10/月 |

---

## 機能

| 機能 | 説明 |
|------|------|
| **25+チャンネル** | Telegram（Whisperによる音声→テキスト、インラインボタン）、Discord（スラッシュコマンド+埋め込み）、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat + さらに15（Telegram API、Discord API、Slack RTM、WhatsApp Cloud、Matrix CS、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat、Email IMAP、SMS Twilio、Alexa、Google Home、Discord Webhook、Telegram Webhook、Custom Webhook） |
| **RavenFlowゲートウェイ** | 永続ワークフローデーモン（`ravenflow`）— ポート18789でマルチエージェントルーティングエンジン、セッション管理、WebSocketストリーミング、チャンネル起点ディスパッチ、サンドボックスポリシー |
| **RavenCodeエージェント** | 自律コーディングエージェント（`ravencode`）— インタラクティブREPL、ストリーミング応答、インラインツール呼び出し、LSP拡張。コマンド: `/multisession`、`/plan`、`/safe`、`/fast`、`/enrich`、`/exit` |
| **LSP自動拡張** | `enrich_context()`がプロジェクトをスキャンし、言語を検出し、LSPサーバー（pyright、typescript-language-server、gopls、rust-analyzer）を起動してシンボルを収集 |
| **並列マルチセッション** | `SessionManager` — 並行 `ManagedSession` タスク、abort/cleanup、シングルトンパターン |
| **Canvasビジュアルワークスペース** | リッチコンポーネントをレンダリング: テキスト、コードブロック、表、mermaid図、リンク、画像、リスト、アラート。ターミナルまたはブラウザHTMLに出力 |
| **Nodes分散実行** | リモートノードの登録/解除、ノード間のタスク実行、全登録エンドポイントへのブロードキャスト |
| **音声入出力** | ウェイクワード（"Raven"、"Hey Raven"、"OK Raven"）、STT（Whisper、Google、Azure、Vosk）、TTS（ElevenLabs、gTTS、システムSAPI、Edge）、マイク録音 |
| **サンドボックスセキュリティポリシー** | 5つのポリシー（main、non-main、code-exec、web-browsing、read-only）— ツール許可/拒否、ネットワーク制御、リソース制限。実行時に変更可能 |
| **Cron / スケジューリング** | `cron_schedule`/`cron_list`/`cron_cancel`ツールで繰り返しタスクをスケジュール（APSchedulerベース） |
| **統合ランチャー** | `main.py` — 全サービスを起動（Raven、RavenFlow、Web UI）+ graceful shutdown |
| **タスクエンジン** | マルチステッププランナー — LLMが目標を分解、ツール選択、実行、結果返却 |
| **モニターエンジン** | 5タイプ: HTTP(S)、資産価格、RSSフィード、ファイル/ディレクトリ、プロセス。トリガー条件、アラート、チェック履歴 |
| **ルーティン** | 自動スケジュール実行: send_briefing、check_email、organize_files、send_message |
| **RAG知識ベース** | 埋め込みエンジン（OpenAI + ローカル）、ベクトルストア、ドキュメントチャンキング（PDF/TXT/コード）、セマンティック検索 |
| **ワークスペーススキル** | `workspace/skills/`内のスキル: 暗号通貨、朝のブリーフィング、Web検索。SKILL.mdから自動読み込み |
| **Webダッシュボード + IDE** | React 19 + Vite + Tailwind + Monaco Editor: ダッシュボード、チャット、タスク、モニター、ルーティン、コードセッション、設定、IDE（エディタ+ターミナル+AIサイドバー） |
| **認証とRBAC** | マルチユーザー認証、4ロール（admin/user/viewer/banned）、16権限、Bearerトークン |
| **エンタープライズ基盤** | サーキットブレーカー、HTTPプール、レートリミッター、指数バックオフリトライ、監査ログ（20イベントタイプ）、Prometheusメトリクス、ヘルスチェック |
| **プラグインシステム** | 10プラグイン — browser、code、cron、files、git、memory、api、ocr、process、sessions。ケイパビリティベースのサンドボックス制御 |
| **安全性** | DMペアリング、チャンネル許可リスト、Fernet暗号化、レート制限、サブプロセス/Dockerサンドボックス |
| **セキュリティポリシー** | ToolPolicyEvaluator、exec.security（deny/ask/full）、deny > allow優先度、workspaceOnly FS、contextVisibility、sanitize_external_content、セキュリティ監査CLI |

---

## CLI

```
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
raven code                     インタラクティブコーディングREPL
raven code --project <dir>     プロジェクトディレクトリでREPL起動
raven code --plan              プランのみモード（書き込みなし）
raven code --safe              セーフモード（書き込み前に確認）
raven code --parallel          並列マルチセッションを有効化
raven code index <path>        コードインデックス
raven code search <query>      コード検索
raven code review <file>       ファイルレビュー
raven routine list             ルーティン一覧
raven routine add ...          ルーティン追加
raven security audit           セキュリティ監査
raven security audit --deep    詳細監査（ネットワーク、環境、依存関係）
raven security audit --fix     自動修正
raven flow serve --port 18789  RavenFlowゲートウェイデーモンを起動
raven flow ask <message>       実行中のゲートウェイにメッセージを送信
raven flow sessions            アクティブなFlowセッションを一覧

ravencode tui                  インタラクティブTUI
ravencode serve                ヘッドレスHTTPサーバー
ravencode web                  Webインターフェース
ravencode session list         保存済みセッションを一覧
ravencode auth login           APIキーを設定

ravenflow --port 18789         RavenFlowゲートウェイデーモンを起動
ravenflow serve --port 18789   RavenFlowゲートウェイデーモンを起動
```

## チャットコマンド

```
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
/pair <code>         ユーザーペアリング
```

---

## アーキテクチャ

```mermaid
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
```

## プロジェクト構造

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

## 技術スタック

| レイヤー | 技術 |
|----------|------|
| **バックエンド** | Python 3.11+, FastAPI, asyncio, SQLite（デフォルト）+ PostgreSQL（オプション） |
| **LLM** | Ollama（ローカル）→ OpenRouter → Anthropic → OpenAI（フェイルオーバー） |
| **メモリ** | SQLite / PostgreSQL + ChromaDB + numpyベクトルストア |
| **RAG** | Qdrantベクトルストア、インメモリフォールバック、n-gram埋め込み |
| **認証** | bcrypt, JWT (HS256), RBAC（4ロール、16権限） |
| **フロントエンド** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **チャンネル** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPIデーモン（ポート18789）、ルーティングエンジン、WebSocketストリーミング、マルチエージェントディスパッチ |
| **RavenCode** | インタラクティブREPL、LSP自動拡張（pyright/tsserver/gopls/rust-analyzer）、並列マルチセッション、plan/safe/fastモード、30+ツール |
| **Canvas** | リッチコンポーネントレンダリング（コード、表、mermaid、画像、リンク、リスト、アラート）、HTML + ブラウザ出力 |
| **Nodes** | 分散ノードレジストリ、ブロードキャスト実行、非同期HTTPディスパッチ |
| **音声** | WakeWordDetector（speech_recognition）、Whisper/Google/Azure/Vosk STT、ElevenLabs/gTTS/SAPI/Edge TTS |
| **サンドボックスポリシー** | 5つのポリシープロファイル（main/non-main/code-exec/web-browsing/read-only）、実行時ツール許可/拒否 |
| **メッセージブローカー** | NATS + JetStream（オプション、分散モード） |
| **レジリエンス** | サーキットブレーカー、レートリミッター、指数バックオフリトライ、監査ログ（20イベントタイプ）、Prometheusメトリクス、ヘルスチェック |
| **可観測性** | OpenTelemetry（トレース + メトリクス）、health/readyプローブ |
| **セキュリティ** | レート制限、JWT認証、DMペアリング、Fernet暗号化、RBAC、プラグインサンドボックス、ToolPolicyEvaluator（deny/allow）、execセキュリティポリシー（deny/ask/full）、contextVisibility、ワークスペース分離、セキュリティ監査CLI |
| **CI/CD** | GitHub Actions — 並列lint + typecheck + test、Allureレポート、Codecov |
| **デプロイ** | Docker, docker-compose, systemd |
| **テスト** | pytest（4593+テスト、Allureレポート）、Vitest（React） |

---

## RavenCode — ターミナルコーディングエージェント

Raven AIは `raven code` — フル機能のインタラクティブターミナルコーディングエージェントを搭載しています:

```bash
# REPLを起動
raven code --project ./my-project

# REPL内:
raven@project> FastAPIでREST APIを作成
# ... 応答をストリーミングし、ツールを呼び出し、ファイルをインライン編集

# 組み込みコマンド:
/help          利用可能なコマンドを表示
/multisession  サブタスクを並列実行
/plan          プランのみモードへ切り替え（書き込みなし）
/safe          セーフモードへ切り替え（書き込み前に確認）
/fast          高速モードへ切り替え（拡張をスキップ）
/enrich        LSP分析を更新
/session <id>  並列セッションに切り替え
/exit          終了
```

### RavenFlowゲートウェイ

WebSocketストリーミング対応のマルチエージェントオーケストレータデーモン:

```bash
# ゲートウェイを起動（単独コマンド）
ravenflow --port 18789

# またはメインCLI経由
raven flow serve --port 18789

# エージェントにメッセージを送信
raven flow ask "READMEを要約して"

# アクティブなセッションを一覧
raven flow sessions
```

### Canvasビジュアルワークスペース

エージェントから直接リッチなビジュアルコンポーネントをレンダリング:

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### 統合ランチャー

単一の `main.py` ランチャーがすべてのサービスを起動します:
```bash
python main.py --web-port 5173 --flow-port 18789
```

---

## お問い合わせ

<div align="center">
  <p>
    <b>Raven AI</b> — <a href="https://github.com/ssrjkk">@ssrjkk</a> によって開発
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    アイデアやバグがありますか？→ <a href="https://github.com/ssrjkk/raven/issues">Issueを開く</a>
  </p>
  <p>
    貢献したいですか？→ <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>24/7のパーソナルAIを必要とする開発者のために作られました</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)
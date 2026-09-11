<div align="center">
  <h1>Raven AI</h1>
  <p><i>二合一: <b>RavenCode</b> (opencode替代 — 自主编码代理) + <b>RavenFlow</b> (openclaw替代 — 持久化工作流网关). 25+渠道. 任务. 监控. RAG. 语音. Web仪表板.</i></p>

  <a href="#features">功能</a> •
  <a href="#quickstart">快速开始</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">架构</a> •
  <a href="#tech-stack">技术栈</a> •
  <a href="#license">许可证</a>

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

## 演示

<p align="center">
  <i>📺 查看Raven的实际操作（30秒演示GIF — 即将推出）</i>
</p>

```text
$ raven "解释这个代码库并修复失败的测试"
🐦 Raven 正在分析你的项目...
   → LSP增强: 检测到3种语言
   → 规划调试会话...
   → 运行 pytest — 发现1个失败
   → 修复 test_users.py 中的断言
   → 已打开PR: #42

$ raven
🐦 交互式REPL — 输入你的任务或/help
  >
```

---

## 为什么选择 Raven AI？

**Raven AI** 不仅仅是一个机器人。它是一个完整的企业级自动化AI助手，在你的服务器上24/7运行。

它能思考。它能规划。它能行动。它能说话。它能流转。

- **在25+渠道中通信** — Telegram, Discord, Slack, WhatsApp, Matrix, Google Chat, Signal, IRC, Teams, Feishu, LINE, 网页聊天 + 另外15个
- **RavenCode代理** — 自主编码代理 (`ravencode`)，LSP自动增强，并行多会话，plan/safe/fast模式，30+工具
- **RavenFlow网关** — 持久化工作流守护进程 (`ravenflow`)，多代理路由，WebSocket流式传输，会话管理
- **Canvas可视工作空间** — 在终端或浏览器中渲染丰富组件（代码、表格、mermaid图、图片、警报）
- **Nodes分布式执行** — 注册、注销、广播并行在远程节点上执行
- **语音输入/输出** — 唤醒词（"Raven"、"Hey Raven"），STT（Whisper/Google/Azure/Vosk），TTS（ElevenLabs/gTTS/system/Edge）
- **执行任务** — 构建分步计划，用工具执行每一步，返回结果
- **运行监控** — 检测网站、检查价格、RSS、文件、进程并发送警报
- **定时任务** — 早间简报、邮件检查、文件整理
- **RAG记忆** — 文档语义搜索、PDF/代码分块、对话记忆
- **Web仪表板** — React 19 + Monaco IDE + Tailwind仪表板
- **多用户 + RBAC** — 管理员、用户、查看者，基于角色的访问控制
- **安全策略** — 5个沙盒配置文件（main、non-main、code-exec、web-browsing、read-only），按会话进行工具允许/拒绝

---

## 快速开始

```bash
pip install raven-agent
# 或用于开发：pip install -e .
cp .env.example .env
# 编辑 .env — 至少添加一个LLM API密钥
raven onboard   # 交互式设置向导（LLM、Telegram、渠道）
raven start     # 启动整个平台

# 或使用独立的入口点：
ravencode tui   # RavenCode — 交互式编码代理
ravenflow       # RavenFlow — 持久化工作流网关
```

### 端口

| 端口 | 服务 | 描述 |
|------|------|------|
| **18888** | Web UI | 网页聊天、仪表板、Monaco IDE、设置 |
| **18789** | RavenFlow 网关 | 多智能体协调器守护进程，支持WebSocket流式传输 |

在浏览器中打开：
- **http://localhost:18888** — 网页聊天
- **http://localhost:18888/dashboard** — 仪表板
- **http://localhost:18888/ide** — Monaco编辑器（含AI侧边栏）

### Docker

```bash
docker compose up
```

### PostgreSQL（可选，替换SQLite）

Raven默认在SQLite中存储各服务的数据。设置 `DATABASE_URL`（或将 `postgresql://`
DSN作为存储的 `db_path` 传入）即可对所有核心存储（任务、监控、定时任务、认证、
会话、outbox、分析、persister）使用PostgreSQL。

```bash
pip install "raven-agent[postgres]"   # 安装 asyncpg

# 启动本地Postgres（user/password/db = raven）
docker compose -f docker-compose.postgres.yml up -d

# 在 .env 中
DATABASE_URL=postgresql://raven:raven@localhost:5432/raven
```

首次连接时自动运行迁移；不会从SQLite迁移数据。

### Web仪表板（开发）

```bash
cd web
npm install
npm run dev    # http://localhost:5173（代理到 :18888）
```

---

## 对比

| 功能 | Raven AI | Open Interpreter | AutoGen | ChatGPT | Copilot |
|------|----------|------------------|---------|---------|---------|
| 自托管 | ✅ 100% | ✅ | ❌ 云 | ❌ 云 | ❌ 云 |
| 25+渠道 | ✅ | ❌ | ❌ | ✅ 仅web | ❌ |
| 带LSP的编码代理 | ✅ | ❌ | ❌ | ❌ | ✅ 基础版 |
| 多代理编排 | ✅ RavenFlow | ❌ | ✅ | ❌ | ❌ |
| 语音 + 唤醒词 | ✅ | ❌ | ❌ | ✅ Voice | ❌ |
| 监控与警报 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 定时任务 | ✅ | ❌ | ❌ | ❌ | ❌ |
| RAG（本地优先） | ✅ ChromaDB/Qdrant | ✅ | ❌ | ❌ | ❌ |
| RBAC多用户 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 5个沙盒配置 | ✅ | ❌ | ❌ | ❌ | ❌ |
| Canvas工作区 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 分布式执行 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 离线模式 | ✅ `--ghost` | ✅ | ❌ | ❌ | ❌ |
| Web仪表板 | ✅ React + Monaco | ❌ 仅CLI | ❌ | ✅ | ✅ IDE |
| 开源 | ✅ MIT | ✅ AGPL | ✅ Apache 2 | ❌ | ❌ |
| 免费 | ✅ | ✅ | ✅ | ❌ $20/月 | ❌ $10/月 |

---

## 功能

| 功能 | 描述 |
|------|------|
| **25+渠道** | Telegram（语音→文字通过Whisper，内联按钮）、Discord（斜杠命令+嵌入）、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat + 另外15个（Telegram API、Discord API、Slack RTM、WhatsApp Cloud、Matrix CS、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat、Email IMAP、SMS Twilio、Alexa、Google Home、Discord Webhook、Telegram Webhook、Custom Webhook） |
| **RavenFlow网关** | 持久化工作流守护进程（`ravenflow`），端口18789，多代理路由引擎、会话管理、WebSocket流式传输、按渠道来源分发、沙盒策略 |
| **RavenCode代理** | 自主编码代理（`ravencode`）— 交互式REPL，流式响应，内联工具调用，LSP增强。命令：`/multisession`、`/plan`、`/safe`、`/fast`、`/enrich`、`/exit` |
| **LSP自动增强** | `enrich_context()` 扫描项目、检测语言、启动LSP服务器（pyright、typescript-language-server、gopls、rust-analyzer）、收集文档符号 |
| **并行多会话** | `SessionManager`，带并发的 `ManagedSession` 任务、abort/cleanup、单例模式 |
| **Canvas可视工作区** | 渲染丰富组件：文本、代码块、表格、mermaid图、链接、图片、列表、警报。输出到终端或浏览器HTML |
| **Nodes分布式执行** | 注册/注销远程节点，跨节点执行任务，广播到所有已注册端点 |
| **语音输入/输出** | 唤醒词（"Raven"、"Hey Raven"、"OK Raven"），STT（Whisper、Google、Azure、Vosk），TTS（ElevenLabs、gTTS、系统SAPI、Edge），麦克风录音 |
| **沙盒安全策略** | 5种策略（main、non-main、code-exec、web-browsing、read-only），带工具允许/拒绝、网络控制、资源限制。可运行时更改 |
| **Cron / 调度** | 通过 `cron_schedule`/`cron_list`/`cron_cancel` 工具调度重复任务（基于APScheduler） |
| **统一启动器** | `main.py` — 启动所有服务（Raven、RavenFlow、Web UI），带优雅关闭 |
| **任务引擎** | 多步骤规划器 — LLM将目标分解为步骤，选择工具，执行，返回结果 |
| **监控引擎** | 5种监控类型：HTTP(S)、资产价格、RSS订阅、文件/目录、进程。触发条件、警报、检查历史 |
| **定时任务** | 自动定时运行：send_briefing、check_email、organize_files、send_message |
| **RAG知识库** | 嵌入引擎（OpenAI + 本地）、向量存储、文档分块（PDF/TXT/代码）、语义检索 |
| **工作区技能** | `workspace/skills/` 中的技能：加密货币、早间简报、网络搜索。通过SKILL.md自动加载 |
| **Web仪表板 + IDE** | React 19 + Vite + Tailwind + Monaco Editor：仪表板、聊天、任务、监控、定时任务、代码会话、设置、IDE（编辑器 + 终端 + AI侧边栏） |
| **认证与RBAC** | 多用户认证、4种角色（admin/user/viewer/banned）、16种权限、Bearer令牌 |
| **企业基础设施** | 断路器、HTTP连接池、速率限制器、指数退避重试、审计日志（20种事件类型）、Prometheus指标、健康检查 |
| **插件系统** | 10个插件 — browser、code、cron、files、git、memory、api、ocr、process、sessions。基于能力的沙盒控制 |
| **安全** | DM配对、渠道白名单、Fernet密钥加密、速率限制、子进程/Docker沙盒 |
| **安全策略** | ToolPolicyEvaluator、exec.security（deny/ask/full）、deny > allow优先级、workspaceOnly FS、contextVisibility、sanitize_external_content、安全审计CLI |

---

## CLI

```
raven start                    启动网关
raven stop                     停止
raven status                   系统状态
raven doctor                   诊断
raven onboard                  设置向导
raven agent --message ...      向代理发送消息
raven pairing list             配对请求
raven pairing approve CODE     确认用户
raven models list              可用模型
raven plugins list             已加载插件
raven history SESSION_ID       消息历史
raven db migrate               数据库迁移
raven db backup                数据库备份
raven task list                任务列表
raven task run <goal>          运行任务
raven task show <id>           任务详情
raven task cancel <id>         取消任务
raven monitor list             监控列表
raven monitor add ...          添加监控
raven code                     交互式编码REPL
raven code --project <dir>     在项目目录启动REPL
raven code --plan              仅计划模式（不写入）
raven code --safe              安全模式（写入前确认）
raven code --parallel          启用并行多会话
raven code index <path>        索引代码
raven code search <query>      搜索代码
raven code review <file>       审查文件
raven routine list             定时任务列表
raven routine add ...          添加定时任务
raven security audit           安全检查
raven security audit --deep    深度检查（网络、环境、依赖）
raven security audit --fix     自动修复问题
raven flow serve --port 18789  启动RavenFlow网关守护进程
raven flow ask <message>       向正在运行的网关发送消息
raven flow sessions            列出活动的Flow会话

ravencode tui                  交互式TUI
ravencode serve                无头HTTP服务器
ravencode web                  网页界面
ravencode session list         列出已保存的会话
ravencode auth login           配置API密钥

ravenflow --port 18789         启动RavenFlow网关守护进程
ravenflow serve --port 18789   启动RavenFlow网关守护进程
```

## 聊天命令

```
/status              机器人状态
/new                 新对话
/reset               重置会话
/compact             压缩历史
/task <goal>         执行任务
/monitor list        监控列表
/monitor add <type> <target>  添加监控
/code index [path]   索引代码
/code search <query> 搜索代码
/code review <file>  审查文件
/routine list        定时任务列表
/routine add <action> <sched>  添加定时任务
/help                所有命令
/pair <code>         配对用户
```

---

## 架构

```mermaid
flowchart TB
    subgraph Clients["客户端与渠道"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Core["核心系统"]
        GW["Raven Gateway\n(Python)"]
        AGENT["ReAct Agent\nFSM States"]
        TOOLS["Tool Registry\nPlugin System"]
        MEM["Memory / Context"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT + RBAC"]
    end

    subgraph Observability["可观测性"]
        OTEL["OpenTelemetry\nTraces + Metrics"]
    end

    subgraph Storage["数据层"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM提供商"]
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

## 项目结构

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

## 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3.11+, FastAPI, asyncio, SQLite（默认）+ PostgreSQL（可选） |
| **LLM** | Ollama（本地）→ OpenRouter → Anthropic → OpenAI（故障转移） |
| **记忆** | SQLite / PostgreSQL + ChromaDB + numpy向量存储 |
| **RAG** | Qdrant向量存储、内存回退、n-gram嵌入 |
| **认证** | bcrypt, JWT (HS256), RBAC（4角色，16权限） |
| **前端** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **渠道** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio, 25+ registry |
| **RavenFlow** | FastAPI守护进程（端口18789）、路由引擎、WebSocket流式传输、多代理分发 |
| **RavenCode** | 交互式REPL、LSP自动增强（pyright/tsserver/gopls/rust-analyzer）、并行多会话、plan/safe/fast模式、30+工具 |
| **Canvas** | 丰富组件渲染（代码、表格、mermaid、图片、链接、列表、警报）、HTML + 浏览器输出 |
| **Nodes** | 分布式节点注册表、广播执行、异步HTTP分发 |
| **语音** | WakeWordDetector（speech_recognition）、Whisper/Google/Azure/Vosk STT、ElevenLabs/gTTS/SAPI/Edge TTS |
| **沙盒策略** | 5个策略配置文件（main/non-main/code-exec/web-browsing/read-only）、运行时工具允许/拒绝 |
| **消息代理** | NATS + JetStream（可选，用于分布式模式） |
| **弹性** | 断路器、速率限制器、指数退避重试、审计日志（20种事件类型）、Prometheus指标、健康检查 |
| **可观测性** | OpenTelemetry（追踪 + 指标）、health/ready探针 |
| **安全** | 速率限制、JWT认证、DM配对、Fernet加密、RBAC、插件沙盒、ToolPolicyEvaluator（deny/allow）、exec安全策略（deny/ask/full）、contextVisibility、工作区隔离、安全审计CLI |
| **CI/CD** | GitHub Actions — 并行lint + typecheck + test、Allure报告、Codecov |
| **部署** | Docker, docker-compose, systemd |
| **测试** | pytest（4593+测试，Allure报告）、Vitest（React） |

---

## RavenCode — 终端编码代理

Raven AI 包含 `raven code` — 一个功能齐全的交互式终端编码代理：

```bash
# 启动REPL
raven code --project ./my-project

# 在REPL中：
raven@project> 用FastAPI创建一个REST API
# ... 流式响应，调用工具，内联编辑文件

# 内置命令：
/help          显示可用命令
/multisession  并行运行子任务
/plan          切换仅计划模式（不写入）
/safe          切换安全模式（写入前确认）
/fast          切换快速模式（跳过增强）
/enrich        刷新LSP分析
/session <id>  切换到并行会话
/exit          退出
```

### RavenFlow 网关

带WebSocket流式传输的多代理编排守护进程：

```bash
# 启动网关（独立命令）
ravenflow --port 18789

# 或通过主CLI
raven flow serve --port 18789

# 向代理发送消息
raven flow ask "总结README"

# 列出活动的会话
raven flow sessions
```

### Canvas 可视化工作区

直接从代理渲染丰富的可视化组件：

```python
await canvas_render([
    {"type": "code", "language": "typescript", "content": "const x = 1"},
    {"type": "table", "headers": ["Name", "Value"], "rows": [["a", "1"]]},
    {"type": "mermaid", "content": "graph TD; A-->B"},
])
```

### 统一启动器

单个 `main.py` 启动器可以启动所有服务：
```bash
python main.py --web-port 5173 --flow-port 18789
```

---

## 联系方式

<div align="center">
  <p>
    <b>Raven AI</b> — 由 <a href="https://github.com/ssrjkk">@ssrjkk</a> 开发
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a> •
    <a href="https://t.me/ssrjkk">@ssrjkk</a>
  </p>
  <p>
    有想法或发现bug？→ <a href="https://github.com/ssrjkk/raven/issues">提交Issue</a>
  </p>
  <p>
    想要贡献？→ <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>为需要7x24小时个人AI的开发者而打造</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)
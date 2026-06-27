<div align="center">
  <h1>Raven AI</h1>
  <p><i>企业级个人AI助手。12个渠道。任务引擎。监控。编程助手。RAG知识库。Web仪表板。</i></p>

  <a href="#features">功能</a> •
  <a href="#quickstart">快速开始</a> •
  <a href="#cli">CLI</a> •
  <a href="#architecture">架构</a> •
  <a href="#tech-stack">技术栈</a> •
  <a href="#license">许可证</a>

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

## 为什么选择 Raven AI？

**Raven AI** 不仅仅是一个机器人。它是一个完整的企业级自动化AI助手，在你的服务器上24/7运行。

它能思考。它能规划。它能行动。

- **在12个消息平台中通信** — Telegram、Discord、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE + 网页聊天
- **执行任务** — 将目标分解为步骤，用工具执行每一步，返回结果
- **运行监控** — 检测网站、检查价格、RSS、文件、进程并发送警报
- **编写代码** — 索引代码库、搜索符号、审查文件、管理开发会话
- **定时任务** — 早间简报、邮件检查、文件整理
- **RAG记忆** — 文档语义搜索、PDF/代码分块、对话记忆
- **Web仪表板** — React面板，包含监控、任务管理、监控器和定时任务
- **多用户 + RBAC** — 管理员、用户、查看者，基于角色的访问控制

---

## 快速开始

`ash
pip install raven-agent
# 或用于开发：pip install -e .
cp .env.example .env
# 编辑 .env — 至少添加一个LLM API密钥
raven onboard   # 交互式设置向导（LLM、Telegram、渠道）
raven start
`

在浏览器中打开：
- **http://localhost:18888** — 网页聊天
- **http://localhost:18888/dashboard** — 仪表板

### Docker

`ash
docker compose up
`

### Web仪表板（开发）

`ash
cd web
npm install
npm run dev    # http://localhost:5173（代理到 :18888）
`

---

## 功能

| 功能 | 描述 |
|------|------|
| **12个渠道** | Telegram（语音→文字通过Whisper，内联按钮）、Discord（斜杠命令+嵌入）、Slack、WhatsApp、Matrix、Google Chat、Signal、IRC、Teams、Feishu、LINE、WebChat |
| **任务引擎** | 多步骤规划器 — LLM将目标分解为步骤，选择工具，执行，返回结果 |
| **监控引擎** | 5种监控类型：HTTP(S)、资产价格、RSS订阅、文件/目录、进程。触发条件、警报、检查历史 |
| **编程助手** | 代码索引（AST解析，8种语言），语义搜索，文件审查（LLM驱动），开发会话 |
| **定时任务** | 自动定时运行：send_briefing、check_email、organize_files、send_message |
| **RAG知识库** | 嵌入引擎（OpenAI + 本地），向量存储，文档分块（PDF/TXT/代码），语义检索 |
| **工作区技能** | workspace/skills/中的技能：加密货币、早间简报、网络搜索。通过SKILL.md自动加载 |
| **Web仪表板** | React 19 + Vite + Tailwind：仪表板、聊天、任务、监控、定时任务、代码会话、设置 |
| **认证与RBAC** | 多用户认证，4种角色（admin/user/viewer/banned），16种权限，Bearer令牌 |
| **企业基础设施** | 断路器、HTTP连接池、速率限制器、指数退避重试、审计日志（20种事件类型）、Prometheus指标、健康检查 |
| **插件系统** | 10个插件 — browser、code、cron、files、git、memory、api、ocr、process、sessions。基于功能的沙盒控制 |
| **安全** | DM配对、渠道白名单、Fernet密钥加密、速率限制、子进程/Docker沙盒 |
| **安全策略** | ToolPolicyEvaluator、exec.security（deny/ask/full）、deny > allow优先级、workspaceOnly FS、contextVisibility、sanitize_external_content、安全审计CLI |

---

## CLI

`
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
raven code index <path>        索引代码
raven code search <query>      搜索代码
raven code review <file>       审查文件
raven routine list             定时任务列表
raven routine add ...          添加定时任务
raven security audit           安全检查
raven security audit --deep    深度检查（网络、环境、依赖）
raven security audit --fix     自动修复问题
`

## 聊天命令

`
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
/pair <code>        配对用户
`

---

## 架构

`mermaid
flowchart TB
    subgraph Clients["客户端与渠道"]
        TG[Telegram]
        DC[Discord]
        SL[Slack]
        WA[WhatsApp]
        WB[Web Dashboard\nReact 19 + Vite]
        CLI[CLI / TUI]
    end

    subgraph Gateway["API网关层"]
        GW["Gateway (Go)\n:8000"]
        CB["Circuit Breaker"]
        RL["Rate Limiter"]
        AUTH["Auth Middleware\nJWT Validation"]
    end

    subgraph Services["微服务"]
        AS["Auth Service (Go)\n:8001 — JWT, SQLite, gRPC"]
        AC["Agent Core (Python)\n:8002 — LLM Router"]
        ME["Monitor Engine (Go)\n:8003 — SQLite, NATS"]
        RS["RAG Service (Python)\n:8004 — Qdrant"]
        TE["Task Engine (Python)\n:8005 — SQLite, Outbox, Saga"]
        CS["Code Service (Python)\n:8006 — Sandbox"]
    end

    subgraph Observability["可观测性"]
        OTEL["OTel Collector\n:4317 gRPC / :4318 HTTP"]
        TEMPO["Tempo\nTrace Storage"]
        LOKI["Loki\nLog Aggregation"]
        PROM["Prometheus\n:9090"]
        GRAF["Grafana\n:3000 — Dashboards"]
    end

    subgraph Messaging["消息代理"]
        NATS["NATS / JetStream\n:4222"]
    end

    subgraph Storage["数据层"]
        SQLITE["SQLite\nAuth / Monitor / Task DBs"]
        QDRANT["Qdrant\nVector Store :6333"]
        FS[(File System\nWorkspace / Data)]
    end

    subgraph LLM["LLM提供商"]
        OLLAMA["Ollama (Local)"]
        OR["OpenRouter"]
        ANTH["Anthropic"]
        OPENAI["OpenAI"]
    end

    subgraph AgentSystem["代理系统"]
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

## 项目结构

`
raven/
├── raven/                      # 主要Python包
│   ├── agent/                  ReAct代理、多代理注册、工作区提示词
│   ├── gateway/                消息路由、会话、命令
│   ├── core/
│   │   ├── auth/               认证、RBAC（4角色、16权限）、API令牌
│   │   ├── security/           ToolPolicyEvaluator、PII编辑、安全审计
│   │   ├── task_engine/        规划器、执行器、任务存储
│   │   ├── monitor/            HTTP、价格、RSS、文件、进程监控+条件
│   │   ├── rag/                嵌入引擎、分块、向量存储
│   │   ├── llm.py              LLM提供商（OpenAI、Anthropic、Ollama、OpenRouter）+故障转移
│   │   ├── config.py           Pydantic设置+YAML配置
│   │   └── admin_api.py        管理员REST API
│   ├── channels/               12个渠道、消息总线、CircuitBreakerChannel
│   ├── cli/                    CLI（click + rich）
│   ├── tools/                  插件工具
│   ├── tui/                    终端UI（textual）
│   └── workspace/              工作区管理器、技能、插件加载器
├── services/                   # 微服务（Go + Python）
│   ├── gateway/                Go网关（认证代理、断路器、速率限制器、指标、gRPC）
│   ├── auth/                   Go认证服务（SQLite、JWT、gRPC、Redis速率限制器）
│   ├── agent-core/             Python — LLM路由器（Ollama/OpenAI/Anthropic）、NATS发布/订阅
│   ├── monitor-engine/         Go监控服务（SQLite、NATS、Prometheus）
│   ├── rag-service/            Python — 语义搜索（Qdrant + 内存回退）
│   ├── task-engine/            Python — 任务规划器（SQLite、NATS、幂等性、发件箱、Saga）
│   ├── code-service/           Python — 代码沙盒（子进程、NATS）
│   └── proto/                  Protobuf定义+生成的Go代码
├── web/                        React 19 + Vite + Tailwind仪表板
├── deploy/                     Docker、k8s、systemd、可观测性栈
├── daemon/                     Rust守护进程（ravend）：系统指标、进程管理
├── aios/                       AI-OS-MVP代理框架
└── plugins/                    用户插件
`

## 技术栈

| 层 | 技术 |
|----|------|
| **后端** | Python 3.13+, FastAPI, asyncio, SQLite (modernc.org/sqlite) |
| **LLM** | Ollama（本地）→ OpenRouter → Anthropic → OpenAI（故障转移） |
| **记忆** | SQLite + ChromaDB + numpy向量存储 |
| **RAG** | Qdrant向量存储，内存回退，n-gram嵌入 |
| **认证** | bcrypt, JWT (HS256), gRPC, RBAC（4角色、16权限） |
| **前端** | React 19, Vite 6, Tailwind CSS 4, react-router-dom, Monaco Editor |
| **渠道** | python-telegram-bot, discord.py, slack-sdk, matrix-nio, IRC asyncio |
| **消息代理** | NATS + JetStream（流：agent.response、monitor.check.completed、task.events、auth.user.created） |
| **网关** | Go 1.26 — 断路器、速率限制器、认证代理、gRPC重试、OpenTelemetry |
| **认证服务** | Go 1.26 — SQLite、JWT、gRPC、令牌桶速率限制器、OpenTelemetry |
| **监控引擎** | Go 1.26 — HTTP健康检查、SQLite、NATS事件、Prometheus指标 |
| **弹性** | 断路器、gRPC重试（指数退避）、速率限制器、发件箱模式、Saga模式、幂等性 |
| **可观测性** | OpenTelemetry（追踪+指标）、Prometheus、Grafana（12面板）、Loki、Tempo、健康/就绪探针 |
| **安全** | 速率限制、JWT认证、DM配对、Fernet加密、RBAC、插件沙盒、ToolPolicyEvaluator（deny/allow）、exec安全策略（deny/ask/full）、contextVisibility、工作区隔离、安全审计CLI |
| **CI/CD** | GitHub Actions — 并行Go/Python/web lint+test+build、Allure TestOps、Docker buildx、Codecov、Playwright E2E、k6负载测试 |
| **部署** | Docker（多阶段、精简、非root）、docker-compose（微服务栈）、Kubernetes清单、systemd、launchd |
| **测试** | pytest（800+测试、Allure报告）、Go表驱动测试、Vitest（React）、Playwright（E2E）、k6（负载） |

---

## AI-OS-MVP — 混合架构

Raven AI 现在运行在混合 **AI-OS-MVP** 架构上：

`
raven-ai/
├── aios/                       # AI-OS-MVP桥接（Python）
│   ├── api/bridge.py           # AI网关端点
│   ├── agents/orchestrator.py  # 代理编排器
│   └── runtime/adapter.py      # 统一运行时
├── web/                        # Web IDE（React 19）
│   └── src/pages/IDE.tsx       # 带编辑器和终端的IDE
├── desktop-tauri/              # Tauri桌面（Rust）
├── packages/                   # TypeScript包
│   ├── ai-core/                # AI路由器+提供商
│   ├── agents/                 # 多代理系统
│   ├── runtime/                # 终端、文件系统、docker
│   └── repo/                   # 索引器、AST、嵌入
`

### AI-OS-MVP 快速开始

`ash
# AI网关（桥接Raven）
raven aios gateway --port 3001

# 运行自主代理
raven aios run "创建一个REST API" --agent autonomous

# 执行命令
raven aios exec "npm run dev"

# Web IDE（Monaco编辑器）
cd web && npm install && npm run dev
# 打开 http://localhost:5173/ide
`

---

## 联系方式

<div align="center">
  <p>
    <b>Raven AI</b> — 由 <a href="https://github.com/ssrjkk">@ssrjkk</a> 开发
  </p>
  <p>
    <a href="https://github.com/ssrjkk/raven">GitHub</a> •
    <a href="https://t.me/ssrjkk">Telegram</a> •
    <a href="mailto:ray013lefe@gmail.com">ray013lefe@gmail.com</a>
  </p>
  <p>
    有想法或发现bug？→ <a href="https://github.com/ssrjkk/raven/issues">提交Issue</a>
  </p>
  <p>
    想要贡献？→ <a href="https://github.com/ssrjkk/raven/pulls">Pull Request</a>
  </p>
  <p><i>为需要24/7个人AI的开发者而生</i></p>
</div>

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

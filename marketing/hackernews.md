
**Title:** Raven AI – A self-hosted, multi-agent AI orchestrator with LSP-enriched coding agent

**Body:**
Show HN: Raven AI

I've built an enterprise-grade, self-hosted AI assistant designed to run 24/7 on your own hardware. Instead of just being a chatbot, it's a full orchestrator with a multi-agent gateway (RavenFlow), a coding agent with LSP enrichment (RavenCode), and a visual canvas workspace.

**Architecture highlights:**
- **Backend:** Python 3.13 (FastAPI) for the core agent, Go 1.26 for the high-performance gateway, monitors, and auth service.
- **Message Broker:** NATS + JetStream for event-driven communication between agents and channels.
- **Frontend:** React 19 + Vite + Tailwind, bundled into a Tauri (Rust) desktop app.
- **Security:** 5 sandbox profiles (main, non-main, code-exec, web-browsing, read-only) with runtime tool allow/deny policies.
- **Local-First:** Supports Ollama for 100% offline operation, with ChromaDB/Qdrant for RAG.

It supports 25+ channels (Telegram, Discord, Slack, Matrix, etc.) and includes tools for task execution, monitoring, and scheduled routines.

GitHub: https://github.com/ssrjkk/raven
Landing: https://ssrjkk.github.io/raven/

I'm particularly interested in feedback on the NATS integration and the LSP enrichment approach for the coding agent.

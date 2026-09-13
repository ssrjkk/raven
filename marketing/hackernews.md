
**Title:** Raven AI – A self-hosted, multi-agent AI orchestrator with LSP-enriched coding agent

**Body:**
Show HN: Raven AI

I've built an enterprise-grade, self-hosted AI assistant designed to run 24/7 on your own hardware. Instead of just being a chatbot, it's a full orchestrator with a multi-agent core, a coding agent with LSP enrichment (RavenCode), and a visual canvas workspace.

**Architecture highlights:**
- **Backend:** A single-process Python 3.11+ (FastAPI) monolith for the core agent, the 15 channel adapters, and the task/monitor/routine engines. No microservices to deploy.
- **Agent core:** ReAct planner + 30+ tools, with `ModelFailover` + circuit breakers across 10 LLM providers (OpenRouter, Anthropic, OpenAI, Ollama, Groq, Bedrock, Vertex…).
- **Frontend:** React 19 + Vite 6 + Tailwind 4 SPA, served by the same gateway process.
- **Security:** sandbox profiles (main, non-main, code-exec, web-browsing, read-only) with runtime tool allow/deny policies, SSRF guards on every outbound request, and RBAC.
- **Local-First:** Supports Ollama for 100% offline operation, with a local JSON embedding store + BM25 for RAG (no external vector DB).

It supports 15 channels (Telegram, Discord, Slack, WhatsApp, Matrix, Signal, Teams, IRC, and more) and includes tools for task execution, monitoring, and scheduled routines.

GitHub: https://github.com/ssrjkk/raven
Landing: https://ssrjkk.github.io/raven/

I'm particularly interested in feedback on the channel supervision (heartbeats + rate limiting) and the LSP enrichment approach for the coding agent.

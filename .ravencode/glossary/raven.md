# Raven AI Glossary

## Core Concepts

- **Raven AI**: Self-hosted personal AI assistant
- **Agent**: AI-powered autonomous worker (ReAct agent)
- **Channel**: Communication platform (Telegram, Discord, etc.)
- **Task Engine**: Multi-step planner and executor
- **Monitor**: Automated watcher for conditions and alerts
- **Routine**: Scheduled automated actions
- **RAG**: Retrieval-Augmented Generation for memory
- **Tool**: Plugin-based capability (browser, code, git, etc.)
- **Plugin**: Extensible module with manifest.json
- **Skill**: Workspace-specific knowledge in SKILL.md

## Architecture

- **Gateway**: FastAPI HTTP server, auth, rate limiting, SSE streaming
- **Agent Core**: LLM router, ReAct agent loop, multi-model orchestration
- **MCP Server**: Model Context Protocol over stdio and HTTP (66 tools)
- **RavenCode**: Autonomous coding agent with workspace confinement
- **Channels**: 15 messaging adapters (Telegram, Discord, Slack, etc.)
- **Tools**: File, shell, git, web, code analysis, testing, memory, routines
- **Task Engine**: Planner with outbox/saga patterns
- **Monitor**: Health checks and condition watchers

## Security

- **ToolPolicyEvaluator**: deny/ask/full policy engine
- **RBAC**: 4 roles (admin, user, viewer, banned), 16 permissions
- **Fernet**: Symmetric encryption for secrets
- **DM Pairing**: User-device binding protocol
- **SSRF Guard**: Blocks private IP outbound requests

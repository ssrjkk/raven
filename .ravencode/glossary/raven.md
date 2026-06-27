# Raven AI Glossary

## Core Concepts

- **Raven AI**: Enterprise-grade personal AI assistant
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

- **Gateway (Go)**: API gateway, auth proxy, rate limiter
- **Agent Core (Python)**: LLM router, ReAct agent
- **Monitor Engine (Go)**: Health checks, price monitors
- **RAG Service (Python)**: Semantic search with Qdrant
- **Task Engine (Python)**: Planner with outbox/saga patterns
- **Code Service (Python)**: Sandboxed code execution
- **Auth Service (Go)**: JWT, gRPC, RBAC
- **Daemon (Rust)**: System metrics, process management

## Security

- **ToolPolicyEvaluator**: deny/ask/full policy engine
- **RBAC**: 4 roles (admin, user, viewer, banned), 16 permissions
- **Fernet**: Symmetric encryption for secrets
- **DM Pairing**: User-device binding protocol
- **SSRF Guard**: Blocks private IP outbound requests

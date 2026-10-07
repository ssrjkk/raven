# Raven AI

_by [@ssrjkk](https://github.com/ssrjkk)_

**Personal AI Assistant — Any Channel. Any Platform.**

Raven AI is a personal AI assistant you run on your own infrastructure. It connects to the messaging channels you already use — Telegram, Discord, Slack, WhatsApp, and more — and provides a unified AI-powered assistant experience.

## Key Features

- **Multi-channel** — 15 messaging channels: Telegram, Discord, Slack, WhatsApp, Matrix, IRC, Signal, Google Chat, Feishu, LINE, Microsoft Teams, GitHub, GitLab, email, and a built-in web chat
- **Autonomous coding agent** — RavenCode: streaming ReAct loop, 66 tools, LSP auto-enrichment for Python/TypeScript/Go/Rust, parallel sub-sessions, plan/safe/fast modes
- **MCP server** — `raven-mcp` and `ravencode-mcp` expose all tools over stdio or HTTP JSON-RPC for Claude Desktop, Qoder, opencode, Cursor, and any MCP client
- **Tool system** — 66 built-in tools: files, shell, git, web search, code analysis, testing, memory, routines, monitors
- **Multi-agent** — Route users to purpose-specific agents
- **Security first** — DM pairing, JWT auth with roles, per-tool allow/deny policy, sandboxed execution, SSRF guard, Fernet-encrypted secrets
- **Self-hosted** — One Python process on your own server. SQLite or PostgreSQL, 10 LLM providers behind one router with circuit breakers
- **Extensible** — Plugin SDK, skill registry, webhook system

## Quick Start

```bash
pip install -e ".[dev]"

raven onboard
raven start
```

## Architecture

Raven uses a **Gateway** architecture:
- **Gateway** — central message orchestrator (FastAPI, single process)
- **Channels** — 15 messaging platform adapters
- **RavenCode** — autonomous coding agent (ReAct loop, LSP, 66 tools, sessions)
- **MCP servers** — `raven-mcp` and `ravencode-mcp` for editor integration
- **Agents** — session-aware AI workers with tool access
- **Tools** — 66 capability plugins (files, code, browser, etc.)
- **Security** — policy engine, audit, PII redaction, sandbox, SSRF guard
- **LLM router** — 10 providers with circuit breakers and failover

## Supported Channels

Telegram · Discord · Slack · WhatsApp · Matrix · IRC · Signal · Google Chat · Feishu · LINE · Microsoft Teams · GitHub · GitLab · Email · WebChat

## License

MIT

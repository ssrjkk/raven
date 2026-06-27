# Raven AI — Project Context

## Overview

Raven AI is an enterprise-grade personal AI assistant that operates 24/7 across 12 messaging channels. It combines a ReAct agent, task engine, monitors, coding assistant, RAG knowledge base, and web dashboard in a hybrid microservices architecture.

## Architecture

```
Clients (Telegram, Discord, Slack, Web, CLI)
    │
    ▼
Gateway (Go) — circuit breaker, rate limiter, JWT auth proxy
    │
    ▼
┌──────────────────────────────────────────────┐
│ Agent Core (Python) — LLM router, ReAct agent│
│ Monitor Engine (Go) — SQLite, NATS, metrics  │
│ RAG Service (Python) — Qdrant, embeddings    │
│ Task Engine (Python) — planner, outbox, saga │
│ Code Service (Python) — sandboxed execution  │
│ Auth Service (Go) — JWT, gRPC, RBAC          │
└──────────────────────────────────────────────┘
    │
    ▼
NATS / JetStream — message broker
OTel / Prometheus / Grafana — observability
SQLite / Qdrant — storage
```

## Key Decisions

- **Hybrid monorepo**: Python (core), Go (high-throughput services), Rust (daemon), TypeScript (web)
- **LLM failover**: Ollama (local) → OpenRouter → Anthropic → OpenAI
- **Message broker**: NATS + JetStream for event-driven communication between services
- **Security first**: ToolPolicyEvaluator, RBAC, Fernet encryption, SSRF guard, workspace isolation
- **Plugin system**: Capability-based sandbox with manifest.json discovery

## Development

```bash
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with LLM keys
raven start
```

See [AGENTS.md](AGENTS.md) for detailed agent guidelines and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow.

# Raven AI — Project Context

## Overview

Raven AI is a self-hosted personal AI assistant that operates 24/7 across 15 messaging channels. It combines a ReAct agent, task engine, monitors, coding assistant (RavenCode), RAG knowledge base, and web dashboard in a single Python monolith.

## Architecture

```
Clients (Telegram, Discord, Slack, Web, CLI, …) — 15 channels
    │
    ▼
Raven Gateway (FastAPI, single process)
    ├── Auth (JWT + RBAC)
    ├── Circuit breaker + rate limiter (token bucket)
    ├── Channel guardian (heartbeat + auto-restart)
    └── Web dashboard (React SPA, served at /)
    │
    ▼
Agent Core
    ├── LLM router (failover across 10 providers)
    ├── ReAct agent / RavenCode coding agent
    ├── Task engine (planner, executor)
    └── Routine + monitor engines
    │
    ▼
Tools (assistant 30+ / coding-agent 50+)
    │
    ▼
Storage: SQLite/PostgreSQL, JSON vector store + BM25
Observability: OTel / Prometheus / structured logs
```

## Key Decisions

- **Single-process monolith** (Python). Optional containers for PostgreSQL, NATS, Prometheus/Grafana via docker-compose — no hard service-mesh dependency
- **LLM failover**: first healthy provider wins; circuit breaker + rate-limit retry/backoff
- **Local-first storage**: JSON vector store + BM25 (no external vector DB required)
- **Security by design**: ToolPolicyEvaluator, RBAC, Fernet encryption, SSRF guard, workspace isolation, sandbox profiles
- **Plugin system**: capability-based sandboxed plugins (10 built-in)

## Development

```bash
pip install -e ".[dev]"
cd web && npm install && cd ..
cp .env.example .env
# Edit .env with LLM keys
python scripts/check_all.py --quick
raven start
```

See [AGENTS.md](AGENTS.md) for detailed agent guidelines and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow.
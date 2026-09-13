# Raven AI — Project Specification

## Architecture Overview

Raven AI is a single-process Python monolith: a FastAPI gateway that connects messaging channels to agent cores (ReAct agent + RavenCode coding agent), with a React SPA served by the gateway itself. Optional containers (PostgreSQL, NATS, Prometheus/Grafana) can be attached via docker-compose when needed.

### Core Principles

1. **Async-first**: All I/O operations use asyncio
2. **Security by design**: Every tool/plugin goes through policy evaluation
3. **Plugin extensibility**: Capability-based sandboxed plugins
4. **Observability**: OpenTelemetry traces + Prometheus metrics + structured logging

### Runtime Layout

| Component | Language | Persistence |
|-----------|----------|-------------|
| Raven Gateway (FastAPI, port 18888) | Python | - |
| Channels (15 adapters) | Python | - |
| Agent core + LLM router | Python | - |
| RavenCode (coding agent) | Python | - |
| Task / Routine / Monitor engines | Python | SQLite/PostgreSQL |
| RAG (embeddings + BM25 + JSON store) | Python | data/*.json |
| Web dashboard (React SPA) | TypeScript | - |

### Data Flow

1. User message → Channel → Gateway (auth, rate limit) → Agent Core
2. Agent Core → LLM Provider → ReAct Agent (tool selection)
3. Tool execution → Task Engine (if multi-step) or direct
4. Response → Gateway → Channel → User
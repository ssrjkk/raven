# Raven AI — Project Specification

## Architecture Overview

Raven AI uses a microservices architecture connected via NATS message broker, with a Go API gateway for auth/rate-limiting.

### Core Principles

1. **Async-first**: All I/O operations use asyncio (Python) or goroutines (Go)
2. **Security by design**: Every tool/plugin goes through policy evaluation
3. **Plugin extensibility**: Capability-based sandboxed plugins
4. **Observability**: OpenTelemetry traces + Prometheus metrics + structured logging

### Service Mesh

| Service | Language | Port | Protocol | Persistence |
|---------|----------|------|----------|-------------|
| Gateway | Go | 8000 | HTTP/gRPC | - |
| Auth | Go | 8001 | gRPC | SQLite |
| Agent Core | Python | 8002 | HTTP | - |
| Monitor | Go | 8003 | HTTP | SQLite |
| RAG | Python | 8004 | HTTP | Qdrant |
| Task | Python | 8005 | HTTP | SQLite |
| Code | Python | 8006 | HTTP | - |

### Data Flow

1. User message → Channel → Gateway (auth, rate limit) → Agent Core
2. Agent Core → LLM Provider → ReAct Agent (tool selection)
3. Tool execution → Task Engine (if multi-step) or direct
4. Response → Gateway → Channel → User

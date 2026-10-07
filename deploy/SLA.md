# Raven Service SLA/SLO

## Gateway (FastAPI)
- **p95 latency**: <200ms (internal), <500ms (external webhooks)
- **Error rate**: <0.1% (5xx), <1% (4xx)
- **Throughput**: 500 req/s nominal, 1000 req/s burst
- **Availability**: 99.9%

## Agent Core
- **p95 latency**: <2s (LLM first token), <10s (full response)
- **Error rate**: <1% (LLM errors excluded from SLO)
- **Throughput**: 50 concurrent sessions
- **Availability**: 99.5%

## MCP Server
- **p95 latency**: <100ms (tool call dispatch)
- **Error rate**: <0.5%
- **Throughput**: 200 tool calls/min
- **Availability**: 99.9%

## Task Engine
- **p95 latency**: <100ms (submit), <30s (execute)
- **Error rate**: <0.5%
- **Throughput**: 100 tasks/min
- **Availability**: 99.5%

## Tool Execution
- **p95 latency**: <5s (shell/code execution)
- **Error rate**: <1%
- **Throughput**: 30 executions/min
- **Availability**: 99.5%

## Monitor
- **p95 latency**: <500ms (check creation), <5s (check execution)
- **Error rate**: <0.5%
- **Throughput**: 1000 checks/min
- **Availability**: 99.9%

## External Dependencies (optional)
- **Redis**: 99.9% uptime, <5ms ops (caching, rate-limit backing)
- **Postgres**: 99.9% uptime (replaces SQLite for production)

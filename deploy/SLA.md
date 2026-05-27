# Raven Service SLA/SLO

## Gateway
- **p95 latency**: <200ms (internal), <500ms (external webhooks)
- **Error rate**: <0.1% (5xx), <1% (4xx)
- **Throughput**: 500 req/s nominal, 1000 req/s burst
- **Availability**: 99.9%

## Auth
- **p95 latency**: <100ms (token validate), <300ms (login/register)
- **Error rate**: <0.05%
- **Throughput**: 200 req/s
- **Availability**: 99.95%

## Agent Core
- **p95 latency**: <2s (LLM first token), <10s (full response)
- **Error rate**: <1% (LLM errors excluded from SLO)
- **Throughput**: 50 concurrent sessions
- **Availability**: 99.5%

## Monitor Engine
- **p95 latency**: <500ms (check creation), <5s (check execution)
- **Error rate**: <0.5%
- **Throughput**: 1000 checks/min
- **Availability**: 99.9%

## RAG Service
- **p95 latency**: <300ms (search), <2s (index)
- **Error rate**: <0.1%
- **Throughput**: 100 QPS (query), 10 QPS (index)
- **Availability**: 99.8%

## Task Engine
- **p95 latency**: <100ms (submit), <30s (execute)
- **Error rate**: <0.5%
- **Throughput**: 100 tasks/min
- **Availability**: 99.5%

## Code Service
- **p95 latency**: <5s (execution)
- **Error rate**: <1%
- **Throughput**: 30 executions/min
- **Availability**: 99.5%

## Infrastructure
- **NATS**: 99.99% uptime, <10ms delivery latency
- **Qdrant**: 99.9% uptime, <50ms search latency
- **Traefik**: 99.99% uptime, <1ms routing overhead

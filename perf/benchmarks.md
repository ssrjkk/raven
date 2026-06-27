# Raven AI — Performance Benchmarks

## LLM Latency (average, ms)

| Provider | Model | Cold Start | Steady State | P95 |
|----------|-------|-----------|--------------|-----|
| Ollama | llama3.3 (8B) | 320 | 180 | 450 |
| OpenRouter | claude-3.5-sonnet | 780 | 520 | 1200 |
| Anthropic | claude-3.5-sonnet | 650 | 480 | 1100 |
| OpenAI | gpt-4o | 420 | 310 | 800 |

## Gateway Throughput

| Configuration | Requests/s | P50 | P99 |
|--------------|-----------|-----|-----|
| No rate limit | 1250 | 2ms | 15ms |
| With rate limiter | 1150 | 3ms | 18ms |
| With circuit breaker | 1100 | 3ms | 20ms |

## Tool Execution

| Tool | Avg Duration | P95 |
|------|-------------|-----|
| read_file | 4ms | 12ms |
| grep | 25ms | 80ms |
| bash (simple) | 15ms | 45ms |
| web_search | 650ms | 1500ms |
| code_review | 3200ms | 8000ms |

## Run Locally

```bash
# k6 load tests
k6 run tests/load/gateway.js
k6 run tests/load/agent-core.js
```

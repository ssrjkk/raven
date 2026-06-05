# Raven Observability SDK

Shared resilience primitives for Raven microservices:

- **`circuit_breaker.py`** — Circuit breaker (Closed → Open → Half-Open) with metrics
- **`retry.py`** — Retry with exponential backoff + jitter
- **`outbox.py`** — Transactional outbox pattern
- **`outbox_poller.py`** — SQLite-based outbox poller
- **`idempotency.py`** — Idempotency key middleware
- **`saga.py`** — Saga orchestration for distributed transactions

## Usage

```python
from observability_sdk.circuit_breaker import CircuitBreaker
from observability_sdk.retry import retry

cb = CircuitBreaker(name="my_service", failure_threshold=5, recovery_timeout=30)

@retry(max_attempts=3, base_delay=1.0)
@cb
async def call_external_api():
    ...
```

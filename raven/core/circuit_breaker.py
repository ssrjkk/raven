from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger


class CircuitBreakerState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str):
        self.breaker_name = name
        super().__init__(f"Circuit breaker '{name}' is open")


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
    ):
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_attempts = 0
        self._lock = asyncio.Lock()
        self._metrics: dict[str, int] = {"transitions": 0, "rejected": 0, "successes": 0, "failures": 0}

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        if self._state == CircuitBreakerState.OPEN:
            return not time.monotonic() - self._last_failure_time >= self._recovery_timeout
        return False

    async def call(self, fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
        async with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_attempts = 0
                    self._metrics["transitions"] += 1
                    logger.info("[cb/{}] half-open", self.name)
                else:
                    self._metrics["rejected"] += 1
                    raise CircuitBreakerOpenError(self.name)

        try:
            result = await fn(*args, **kwargs)
        except Exception:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                self._metrics["failures"] += 1
                if self._state == CircuitBreakerState.HALF_OPEN:
                    self._state = CircuitBreakerState.OPEN
                    self._metrics["transitions"] += 1
                elif self._failure_count >= self._failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    self._metrics["transitions"] += 1
                    logger.warning("[cb/{}] open after {} failures", self.name, self._failure_threshold)
            raise

        async with self._lock:
            self._metrics["successes"] += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_attempts += 1
                if self._half_open_attempts >= self._half_open_max:
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._metrics["transitions"] += 1
                    logger.info("[cb/{}] closed after half-open tests", self.name)
        return result

    def reset(self):
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._metrics["transitions"] += 1

    def stats(self) -> dict[str, Any]:
        return {"name": self.name, "state": self._state, **self._metrics}

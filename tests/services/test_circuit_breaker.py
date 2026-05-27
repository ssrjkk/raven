import asyncio
import time

import pytest

from services.observability_sdk.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerState,
)


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_successful_call(self):
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=0.5)
        result = await cb.call(async_success)
        assert result == "ok"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_trips_after_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1.0)

        with pytest.raises(ValueError):
            await cb.call(async_fail)
        assert cb.state == CircuitBreakerState.CLOSED

        with pytest.raises(ValueError):
            await cb.call(async_fail)

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(async_fail)

    @pytest.mark.asyncio
    async def test_half_open_recovers(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1, half_open_max=1)

        with pytest.raises(ValueError):
            await cb.call(async_fail)

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(async_fail)

        await asyncio.sleep(0.15)
        result = await cb.call(async_success)
        assert result == "ok"
        assert cb.state == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_fails_again(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1, half_open_max=1)

        with pytest.raises(ValueError):
            await cb.call(async_fail)

        await asyncio.sleep(0.15)

        with pytest.raises(ValueError):
            await cb.call(async_fail)

        assert cb.state == CircuitBreakerState.OPEN

    def test_metrics(self):
        cb = CircuitBreaker("test")
        stats = cb.stats()
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["rejected"] == 0

    def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb._failure_count = 5
        cb._state = CircuitBreakerState.OPEN
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 0

    def test_is_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=9999)
        cb._failure_count = 5
        cb._state = CircuitBreakerState.OPEN
        cb._last_failure_time = time.monotonic()
        assert cb.is_open

    @pytest.mark.asyncio
    async def test_multiple_concurrent_calls(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=9999)

        with pytest.raises(ValueError):
            await cb.call(async_fail)

        tasks = [cb.call(async_success) for _ in range(5)]
        for t in asyncio.as_completed(tasks):
            with pytest.raises(CircuitBreakerOpenError):
                await t


async def async_success():
    return "ok"


async def async_fail():
    raise ValueError("boom")

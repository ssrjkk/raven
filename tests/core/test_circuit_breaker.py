from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from raven.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitBreakerState


class TestCircuitBreakerState:
    def test_constants(self) -> None:
        assert CircuitBreakerState.CLOSED == "closed"
        assert CircuitBreakerState.OPEN == "open"
        assert CircuitBreakerState.HALF_OPEN == "half_open"


class TestCircuitBreakerOpenError:
    def test_init(self) -> None:
        err = CircuitBreakerOpenError("test-breaker")
        assert err.breaker_name == "test-breaker"
        assert "test-breaker" in str(err)


class TestCircuitBreakerInit:
    def test_defaults(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.name == "test"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.is_open is False

    def test_custom_params(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10.0, half_open_max=2)
        assert cb._failure_threshold == 3
        assert cb._recovery_timeout == 10.0
        assert cb._half_open_max == 2


class TestIsOpen:
    def test_closed_returns_false(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.is_open is False

    def test_open_not_expired_returns_true(self) -> None:
        cb = CircuitBreaker("test", recovery_timeout=60.0)
        cb._state = CircuitBreakerState.OPEN
        cb._last_failure_time = time.monotonic()
        assert cb.is_open is True

    def test_open_expired_returns_false(self) -> None:
        cb = CircuitBreaker("test", recovery_timeout=0.0)
        cb._state = CircuitBreakerState.OPEN
        cb._last_failure_time = 0.0
        assert cb.is_open is False


class TestCall:
    async def test_success_passthrough(self) -> None:
        cb = CircuitBreaker("test")
        fn = AsyncMock(return_value="ok")
        result = await cb.call(fn, "arg1", key="val")
        assert result == "ok"
        fn.assert_awaited_once_with("arg1", key="val")

    async def test_failure_below_threshold_stays_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        fn = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fn)
        assert cb.state == CircuitBreakerState.CLOSED

    async def test_failure_at_threshold_opens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2)
        fn = AsyncMock(side_effect=ValueError("fail"))
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fn)
        assert cb.state == CircuitBreakerState.OPEN

    async def test_open_rejects_calls(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=999.0)
        fn = AsyncMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            await cb.call(fn)
        assert cb.state == CircuitBreakerState.OPEN
        fn2 = AsyncMock(return_value="ok")
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fn2)

    async def test_open_transitions_to_half_open_after_recovery(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0, half_open_max=2)
        fn_fail = AsyncMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            await cb.call(fn_fail)
        assert cb.state == CircuitBreakerState.OPEN
        fn_ok = AsyncMock(return_value="recovered")
        result = await cb.call(fn_ok)
        assert result == "recovered"
        assert cb.state == CircuitBreakerState.HALF_OPEN

    async def test_half_open_success_closes(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0, half_open_max=1)
        fn_fail = AsyncMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            await cb.call(fn_fail)
        assert cb.state == CircuitBreakerState.OPEN
        fn_ok = AsyncMock(return_value="ok")
        result = await cb.call(fn_ok)
        assert result == "ok"
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 0

    async def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0)
        fn_fail = AsyncMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            await cb.call(fn_fail)
        assert cb.state == CircuitBreakerState.OPEN
        with pytest.raises(ValueError):
            await cb.call(fn_fail)
        assert cb.state == CircuitBreakerState.OPEN

    async def test_half_open_needs_multiple_successes(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.0, half_open_max=2)
        fn_fail = AsyncMock(side_effect=ValueError("fail"))
        with pytest.raises(ValueError):
            await cb.call(fn_fail)
        fn_ok = AsyncMock(return_value="ok")
        await cb.call(fn_ok)
        assert cb.state == CircuitBreakerState.HALF_OPEN
        await cb.call(fn_ok)
        assert cb.state == CircuitBreakerState.CLOSED


class TestOnSuccess:
    async def test_closed_stays_closed(self) -> None:
        cb = CircuitBreaker("test")
        await cb.on_success()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._metrics["successes"] == 1

    async def test_half_open_closes(self) -> None:
        cb = CircuitBreaker("test")
        cb._state = CircuitBreakerState.HALF_OPEN
        cb._failure_count = 3
        await cb.on_success()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 0
        assert cb._metrics["transitions"] == 1


class TestOnFailure:
    async def test_below_threshold_stays_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=5)
        await cb.on_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 1

    async def test_at_threshold_opens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2)
        await cb.on_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        await cb.on_failure()
        assert cb.state == CircuitBreakerState.OPEN

    async def test_half_open_reopens(self) -> None:
        cb = CircuitBreaker("test")
        cb._state = CircuitBreakerState.HALF_OPEN
        await cb.on_failure()
        assert cb.state == CircuitBreakerState.OPEN
        assert cb._metrics["transitions"] == 1


class TestTryAcquire:
    async def test_closed_returns_true(self) -> None:
        cb = CircuitBreaker("test")
        assert await cb.try_acquire() is True

    async def test_open_not_expired_returns_false(self) -> None:
        cb = CircuitBreaker("test", recovery_timeout=999.0)
        cb._state = CircuitBreakerState.OPEN
        cb._last_failure_time = time.monotonic()
        assert await cb.try_acquire() is False
        assert cb._metrics["rejected"] == 1

    async def test_open_expired_transitions_to_half_open(self) -> None:
        cb = CircuitBreaker("test", recovery_timeout=0.0)
        cb._state = CircuitBreakerState.OPEN
        cb._last_failure_time = 0.0
        assert await cb.try_acquire() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN


class TestReset:
    async def test_reset(self) -> None:
        cb = CircuitBreaker("test")
        cb._state = CircuitBreakerState.OPEN
        cb._failure_count = 10
        cb.reset()
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb._failure_count == 0
        assert cb._metrics["transitions"] == 1


class TestStats:
    def test_stats(self) -> None:
        cb = CircuitBreaker("test")
        s = cb.stats()
        assert s["name"] == "test"
        assert s["state"] == CircuitBreakerState.CLOSED
        assert s["transitions"] == 0
        assert s["rejected"] == 0
        assert s["successes"] == 0
        assert s["failures"] == 0

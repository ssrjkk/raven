import asyncio

import pytest

from raven.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError


class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == "closed"
        assert not cb.is_open

    async def test_call_success(self):
        async def ok():
            return "ok"

        cb = CircuitBreaker("test")
        result = await cb.call(ok)
        assert result == "ok"

    async def test_call_failure_opens_after_threshold(self):
        async def fail():
            raise ValueError("nope")

        cb = CircuitBreaker("test", failure_threshold=2)
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == "closed"
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == "open"

    async def test_call_rejected_when_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)

        async def fail():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == "open"

        async def ok():
            return "ok"

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(ok)

    async def test_half_open_recovers(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)

        async def first_fail():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(first_fail)
        assert cb.state == "open"

        await asyncio.sleep(0.02)

        async def recovered():
            return "recovered"

        result = await cb.call(recovered)
        assert result == "recovered"
        assert cb.state == "closed"

    async def test_half_open_failure_stays_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)

        async def fail():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail)

        await asyncio.sleep(0.02)

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == "open"

    async def test_half_open_max_respected(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01, half_open_max=1)

        async def fail():
            raise ValueError("nope")

        with pytest.raises(ValueError):
            await cb.call(fail)

        await asyncio.sleep(0.02)

        async def ok_fn():
            return "ok"

        result = await cb.call(ok_fn)
        assert result == "ok"
        assert cb.state == "closed"

    def test_reset(self):
        cb = CircuitBreaker("test")
        cb._state = "open"
        cb.reset()
        assert cb.state == "closed"

    def test_stats(self):
        cb = CircuitBreaker("test")
        assert cb.stats()["rejected"] == 0


class TestCircuitBreakerOpenError:
    def test_message(self):
        err = CircuitBreakerOpenError("my-breaker")
        assert "my-breaker" in str(err)
        assert err.breaker_name == "my-breaker"

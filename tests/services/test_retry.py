import pytest

from services.observability_sdk.retry import DEFAULT_RETRY, FAST_RETRY, NO_RETRY, SLOW_RETRY, RetryPolicy


class TestRetryPolicy:
    @pytest.mark.asyncio
    async def test_success(self):
        result = await DEFAULT_RETRY.execute(async_ok, operation_name="test")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_retries_and_succeeds(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("flaky")
            return "success"

        result = await DEFAULT_RETRY.execute(flaky, operation_name="flaky")
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        with pytest.raises(ConnectionError):
            await DEFAULT_RETRY.execute(async_fail_conn, operation_name="fail-conn")

    @pytest.mark.asyncio
    async def test_no_retry(self):
        with pytest.raises(ConnectionError):
            await NO_RETRY.execute(async_fail_conn, operation_name="no-retry")

    @pytest.mark.asyncio
    async def test_fast_retry(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError("timeout")
            return "ok"

        result = await FAST_RETRY.execute(fail_twice, operation_name="fast")
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_slow_retry_limits(self):
        with pytest.raises(ConnectionError):
            await SLOW_RETRY.execute(async_fail_conn, operation_name="slow")

    @pytest.mark.asyncio
    async def test_non_retryable_exception(self):
        policy = RetryPolicy(max_retries=2, retryable_exceptions=(ConnectionError,))

        with pytest.raises(ValueError):
            await policy.execute(async_fail_val, operation_name="val")


async def async_ok():
    return "ok"


async def async_fail_conn():
    raise ConnectionError("connection lost")


async def async_fail_val():
    raise ValueError("bad value")

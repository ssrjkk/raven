from __future__ import annotations

import pytest
from pytest_benchmark.fixture import BenchmarkFixture


@pytest.mark.benchmark
def test_feature_flags_instantiation(benchmark: BenchmarkFixture) -> None:
    from ravencode.core.feature_flags import FeatureFlags

    def create() -> FeatureFlags:
        return FeatureFlags()

    result = benchmark(create)
    flags = result.all_flags()
    assert set(flags) == {"redis_rate_limiter"}
    assert flags["redis_rate_limiter"] is False


@pytest.mark.benchmark
def test_feature_flags_is_enabled(benchmark: BenchmarkFixture) -> None:
    from ravencode.core.feature_flags import FeatureFlags

    ff = FeatureFlags()
    ff.set("redis_rate_limiter", True)

    def check() -> bool:
        return ff.is_enabled("redis_rate_limiter")

    result = benchmark(check)
    assert result is True


@pytest.mark.benchmark
def test_token_bucket_acquire(benchmark: BenchmarkFixture) -> None:
    from ravencode.core.rate_limiter import TokenBucket

    def create_and_acquire() -> bool:
        bucket = TokenBucket(rate=1_000_000.0, burst=1_000_000)
        return bucket.acquire()

    result = benchmark(create_and_acquire)
    assert result is True

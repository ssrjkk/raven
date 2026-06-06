from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from loguru import logger

T = TypeVar("T")


class RetryPolicy:
    """Configurable retry with exponential backoff and jitter.

    Default: 3 attempts, 1s base backoff, 2x multiplier, 30s max, 0.1 jitter.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        multiplier: float = 2.0,
        jitter: float = 0.1,
        retryable_exceptions: tuple[type[Exception], ...] = (
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or (Exception,)

    async def execute(
        self,
        fn: Callable[..., Awaitable[T]],
        *args,
        operation_name: str = "unknown",
        **kwargs,
    ) -> T:
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (self.multiplier**attempt), self.max_delay)
                    import random

                    jitter_amount = delay * self.jitter
                    actual_delay = delay + random.uniform(-jitter_amount, jitter_amount)
                    logger.warning(
                        "[retry] {} failed (attempt {}/{}): {} — retrying in {:.1f}s",
                        operation_name,
                        attempt + 1,
                        self.max_retries,
                        e,
                        actual_delay,
                    )
                    await asyncio.sleep(max(actual_delay, 0.1))
                else:
                    logger.error(
                        "[retry] {} failed after {} attempts: {}",
                        operation_name,
                        self.max_retries,
                        e,
                    )

        raise last_exception  # type: ignore[misc]


# Predefined policies
FAST_RETRY = RetryPolicy(max_retries=2, base_delay=0.1, max_delay=1.0)
DEFAULT_RETRY = RetryPolicy(max_retries=3, base_delay=1.0, max_delay=30.0)
SLOW_RETRY = RetryPolicy(max_retries=5, base_delay=2.0, max_delay=60.0)
NO_RETRY = RetryPolicy(max_retries=0)

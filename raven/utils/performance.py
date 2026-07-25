from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")


def measure_latency(threshold_ms: float = 50.0) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                if duration_ms > threshold_ms:
                    logger.warning(
                        "SLOW_QUERY: {func_name} took {duration:.2f}ms (threshold: {threshold}ms)",
                        func_name=func.__name__,
                        duration=duration_ms,
                        threshold=threshold_ms,
                    )

        return wrapper

    return decorator

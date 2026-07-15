from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from loguru import logger


def measure_latency(threshold_ms: float = 50.0):
    """
    Декоратор для замера времени выполнения асинхронных функций.
    Логирует предупреждение, если выполнение превышает threshold_ms.
    """
    def decorator(func: Callable[..., Any]):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
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

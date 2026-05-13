from __future__ import annotations

import time
from functools import wraps
from typing import Any, Callable

from loguru import logger


class MetricsCollector:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._errors: dict[str, int] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + 1

    def observe(self, name: str, duration: float, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        if key not in self._latencies:
            self._latencies[key] = []
        self._latencies[key].append(duration)
        if len(self._latencies[key]) > 1000:
            self._latencies[key] = self._latencies[key][-1000:]

    def error(self, name: str, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        self._errors[key] = self._errors.get(key, 0) + 1

    def _key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}{{{','.join(parts)}}}"

    def snapshot(self) -> dict:
        out = {}
        for k, v in self._counters.items():
            out[f"raven_{k}_total"] = v
        for k, vals in self._latencies.items():
            if vals:
                out[f"raven_{k}_count"] = len(vals)
                out[f"raven_{k}_sum"] = sum(vals)
                out[f"raven_{k}_avg"] = sum(vals) / len(vals)
                out[f"raven_{k}_max"] = max(vals)
                out[f"raven_{k}_p99"] = sorted(vals)[int(len(vals) * 0.99)]
        for k, v in self._errors.items():
            out[f"raven_{k}_errors_total"] = v
        return out

    def prometheus(self) -> str:
        lines = ["# HELP raven_ metrics", "# TYPE raven_ counter"]
        for k, v in self._counters.items():
            lines.append(f"raven_{k}_total {v}")
        for k, vals in self._latencies.items():
            if vals:
                lines.append(f"# TYPE raven_{k}_summary")
                lines.append(f"raven_{k}_count {len(vals)}")
                lines.append(f"raven_{k}_sum {sum(vals)}")
        for k, v in self._errors.items():
            lines.append(f"raven_{k}_errors_total {v}")
        return "\n".join(lines) + "\n"

    def clear(self):
        self._counters.clear()
        self._latencies.clear()
        self._errors.clear()


metrics = MetricsCollector()


def timed(name: str, labels: dict[str, str] | None = None) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                metrics.observe(name, time.monotonic() - start, labels)
                return result
            except Exception as e:
                metrics.error(name, labels)
                metrics.observe(name, time.monotonic() - start, labels)
                raise

        @wraps(fn)
        def sync_wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                metrics.observe(name, time.monotonic() - start, labels)
                return result
            except Exception as e:
                metrics.error(name, labels)
                metrics.observe(name, time.monotonic() - start, labels)
                raise

        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper
    return decorator

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from raven.core.llm.protocol import LLMProvider, LLMResponse

_PCounter: Any = None
_PHistogram: Any = None
start_http_server: Any = None
try:
    from prometheus_client import Counter as _PCounter
    from prometheus_client import Histogram as _PHistogram
    from prometheus_client import start_http_server

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


class MetricsCollector:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._errors: dict[str, int] = {}

    def inc(self, name: str, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + 1
        if HAS_PROMETHEUS:
            _prom_inc(name, labels)

    def observe(self, name: str, duration: float, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        if key not in self._latencies:
            self._latencies[key] = []
        self._latencies[key].append(duration)
        if len(self._latencies[key]) > 1000:
            self._latencies[key] = self._latencies[key][-1000:]
        if HAS_PROMETHEUS:
            _prom_observe(name, duration, labels)

    def error(self, name: str, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        self._errors[key] = self._errors.get(key, 0) + 1
        if HAS_PROMETHEUS:
            _prom_inc(f"{name}_errors", labels)

    def _key(self, name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        parts = [f"{k}={v}" for k, v in sorted(labels.items())]
        return f"{name}{{{','.join(parts)}}}"

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in self._counters.items():
            out[f"raven_{k}_total"] = v
        for k, vals in self._latencies.items():
            if vals:
                out[f"raven_{k}_count"] = len(vals)
                out[f"raven_{k}_sum"] = sum(vals, 0.0)
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


_prom_registry: dict[str, Any] = {}


def _prom_inc(name: str, labels: dict[str, str] | None = None):
    if not HAS_PROMETHEUS or _PCounter is None:
        return
    key = name
    if key not in _prom_registry:
        label_names = sorted(labels) if labels else []
        _prom_registry[key] = _PCounter(f"raven_{name}_total", f"Total {name}", label_names)
    counter = _prom_registry[key]
    if labels:
        counter.labels(**{k: labels[k] for k in sorted(labels)}).inc()
    else:
        counter.inc()


def _prom_observe(name: str, duration: float, labels: dict[str, str] | None = None):
    if not HAS_PROMETHEUS or _PHistogram is None:
        return
    key = f"{name}_duration"
    if key not in _prom_registry:
        label_names = sorted(labels) if labels else []
        _prom_registry[key] = _PHistogram(f"raven_{name}_duration_seconds", f"{name} duration", label_names)
    hist = _prom_registry[key]
    if labels:
        hist.labels(**{k: labels[k] for k in sorted(labels)}).observe(duration)
    else:
        hist.observe(duration)


class MetricsServer:
    def __init__(self, port: int = 9090):
        self.port = port
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if not HAS_PROMETHEUS or start_http_server is None:
            logger.warning("prometheus_client not installed — MetricsServer disabled")
            self._started = True
            return
        start_http_server(self.port)
        self._started = True
        logger.info("Prometheus metrics server started on port {}", self.port)

    async def stop(self) -> None:
        self._started = False


class InstrumentedLLMProvider(LLMProvider):
    def __init__(self, provider: LLMProvider, provider_name: str):
        self._wrapped = provider
        self._provider_name = provider_name

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        start = asyncio.get_running_loop().time()
        try:
            result = await self._wrapped.complete(messages, model, tools)
            metrics.inc("llm_complete", {"provider": self._provider_name, "model": model, "status": "ok"})
            return result
        except Exception:
            metrics.inc("llm_complete", {"provider": self._provider_name, "model": model, "status": "error"})
            raise
        finally:
            dur = asyncio.get_running_loop().time() - start
            metrics.observe("llm_request", dur, {"provider": self._provider_name, "model": model})

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[str]:
        start = asyncio.get_running_loop().time()
        sent = 0
        try:
            async for token in self._wrapped.complete_stream(messages, model, tools):
                sent += len(token)
                yield token
            metrics.inc("llm_stream", {"provider": self._provider_name, "model": model, "status": "ok"})
        except Exception:
            metrics.inc("llm_stream", {"provider": self._provider_name, "model": model, "status": "error"})
            raise
        finally:
            dur = asyncio.get_running_loop().time() - start
            metrics.observe("llm_request", dur, {"provider": self._provider_name, "model": model})

    async def cleanup(self):
        await self._wrapped.cleanup()

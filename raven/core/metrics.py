from __future__ import annotations

import threading
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from loguru import logger

P = ParamSpec("P")
T = TypeVar("T")

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


_Labels = tuple[tuple[str, str], ...]
_Key = tuple[str, _Labels]


def _snapshot_labels(labels: _Labels) -> str:
    """The label block as `snapshot()` has always spelled it: `name{k=v,…}`."""
    return "" if not labels else "{" + ",".join(f"{k}={v}" for k, v in labels) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _exposition_labels(labels: _Labels) -> str:
    """The same block as the exposition format requires it: after the full metric name, values quoted."""
    return "" if not labels else "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels) + "}"


def _counter_family(name: str) -> str:
    """The family a counter belongs to, without the `_total` both output surfaces append.

    Publishers spell the name both ways: the gateway calls `inc("messages_received")`, `tool_registry`
    calls `inc("tool_calls_total")`. The second used to be stored as
    `raven_tool_calls_total{category=fs,tool=read_file}_total`, which no analytics query matched, while
    `prometheus_client` stripped the duplicate suffix and exported `raven_tool_calls_total{...}` — so the
    two surfaces of one collector disagreed about which series exist.
    """
    return name[: -len("_total")] if name.endswith("_total") else name


class MetricsCollector:
    def __init__(self):
        self._counters: dict[_Key, int] = {}
        self._latencies: dict[_Key, list[float]] = {}
        self._errors: dict[_Key, int] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, labels: dict[str, str] | None = None):
        name = _counter_family(name)
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
        if HAS_PROMETHEUS:
            _prom_inc(name, labels)

    def observe(self, name: str, duration: float, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        with self._lock:
            if key not in self._latencies:
                self._latencies[key] = []
            self._latencies[key].append(duration)
            if len(self._latencies[key]) > 1000:
                self._latencies[key] = self._latencies[key][-1000:]
        if HAS_PROMETHEUS:
            _prom_observe(name, duration, labels)

    def error(self, name: str, labels: dict[str, str] | None = None):
        key = self._key(name, labels)
        with self._lock:
            self._errors[key] = self._errors.get(key, 0) + 1
        if HAS_PROMETHEUS:
            _prom_inc(f"{name}_errors", labels)

    def _key(self, name: str, labels: dict[str, str] | None) -> _Key:
        return name, tuple(sorted(labels.items())) if labels else ()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {}
            for (name, labels), v in self._counters.items():
                out[f"raven_{name}{_snapshot_labels(labels)}_total"] = v
            for (name, labels), vals in self._latencies.items():
                if vals:
                    key = f"raven_{name}{_snapshot_labels(labels)}"
                    out[f"{key}_count"] = len(vals)
                    out[f"{key}_sum"] = sum(vals, 0.0)
                    out[f"{key}_avg"] = sum(vals) / len(vals)
                    out[f"{key}_max"] = max(vals)
                    out[f"{key}_p99"] = sorted(vals)[int(len(vals) * 0.99)]
            for (name, labels), v in self._errors.items():
                out[f"raven_{name}{_snapshot_labels(labels)}_errors_total"] = v
        return out

    def prometheus(self) -> str:
        """The same numbers in the format a Prometheus scrape parses.

        Labels used to be spelled into the metric name — `raven_messages_received{channel=webchat}_total` —
        which is not a name any parser accepts: the exposition grammar wants the label block after the whole
        name, with quoted values, and a `# TYPE` line per family. So every labelled gateway answered
        `/api/metrics/prometheus` with text whose labelled samples were dropped on parse, while the console's
        own `/api/metrics` JSON kept them: the two surfaces of one collector disagreed about which metrics
        exist. The JSON keeps its spelling because that is what `MetricsSnapshot` consumers read today.
        """
        with self._lock:
            families: dict[str, tuple[str, list[str]]] = {}

            def add(family: str, kind: str, sample: str, labels: _Labels, value: float) -> None:
                families.setdefault(family, (kind, []))[1].append(f"{sample}{_exposition_labels(labels)} {value}")

            for (name, labels), value in self._counters.items():
                add(f"raven_{name}_total", "counter", f"raven_{name}_total", labels, value)
            for (name, labels), vals in self._latencies.items():
                if vals:
                    add(f"raven_{name}", "summary", f"raven_{name}_count", labels, len(vals))
                    add(f"raven_{name}", "summary", f"raven_{name}_sum", labels, sum(vals))
            for (name, labels), value in self._errors.items():
                add(f"raven_{name}_errors_total", "counter", f"raven_{name}_errors_total", labels, value)
            lines: list[str] = []
            for family, (kind, samples) in families.items():
                lines.append(f"# TYPE {family} {kind}")
                lines.extend(samples)
        return "".join(f"{line}\n" for line in lines)

    def clear(self):
        with self._lock:
            self._counters.clear()
            self._latencies.clear()
            self._errors.clear()


metrics = MetricsCollector()


def timed(operation: str, metric: str = "db_query") -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Record one call's latency under `metric`, labelled by operation, and count its failures.

    Latency is recorded even when the call raises; a cancelled call is not a storage failure, so
    only Exception counts as an error.
    """

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            except Exception:
                metrics.error(metric, {"operation": operation})
                raise
            finally:
                metrics.observe(metric, time.perf_counter() - start, {"operation": operation})

        return wrapper

    return decorator


_prom_registry: dict[str, Any] = {}
_prom_schema: dict[str, tuple[str, ...]] = {}
_prom_dropped: set[str] = set()


def _prom_series(maker: Any, key: str, metric_name: str, doc: str, labels: dict[str, str] | None) -> Any:
    """The mirror of one metric name, built with the label names the first call to it carried.

    `prometheus_client` fixes a metric's label names when it is constructed and rejects any call that
    does not match them, so this used to decide the schema from whichever caller arrived first and raise
    for every other shape. Measured: `metrics.observe("llm_request", dur)` from a script that warmed the
    counters made the gateway's own next LLM request die inside its metrics call —
    `ValueError: No label names were set when constructing histogram:raven_llm_request_duration_seconds` —
    and the reverse order raised `counter metric is missing label values` in the pytest session that runs
    `scripts/gen_api_fixtures.py` after the gateway tests. A metric call is on the request path, so the
    shape of an earlier call cannot be allowed to decide whether a later request completes.
    """
    schema = _prom_schema.get(key)
    if schema is None:
        schema = tuple(sorted(labels)) if labels else ()
        _prom_schema[key] = schema
        _prom_registry[key] = maker(metric_name, doc, list(schema))
    return _prom_registry[key]


def _prom_values(key: str, labels: dict[str, str] | None) -> dict[str, str]:
    """Project one call's labels onto the schema the mirror already has.

    A dimension the schema lacks cannot be added after construction, so it is dropped from the mirror and
    said out loud once — the collector's own snapshot keys stay label-for-label exact either way.
    """
    schema = _prom_schema[key]
    given = labels or {}
    extra = sorted(set(given) - set(schema))
    if extra and key not in _prom_dropped:
        _prom_dropped.add(key)
        logger.warning(
            "Prometheus mirror of {} was created without {}; those calls are counted under {} in the mirror, "
            "and metrics.snapshot() keeps the labels",
            key,
            ", ".join(extra),
            ", ".join(f"{name}=''" for name in schema) or "no labels",
        )
    return {name: given.get(name, "") for name in schema}


def _prom_inc(name: str, labels: dict[str, str] | None = None):
    if not HAS_PROMETHEUS or _PCounter is None:
        return
    counter = _prom_series(_PCounter, name, f"raven_{name}_total", f"Total {name}", labels)
    values = _prom_values(name, labels)
    if values:
        counter.labels(**values).inc()
    else:
        counter.inc()


def _prom_observe(name: str, duration: float, labels: dict[str, str] | None = None):
    if not HAS_PROMETHEUS or _PHistogram is None:
        return
    key = f"{name}_duration"
    hist = _prom_series(_PHistogram, key, f"raven_{name}_duration_seconds", f"{name} duration", labels)
    values = _prom_values(key, labels)
    if values:
        hist.labels(**values).observe(duration)
    else:
        hist.observe(duration)


_BOUND_PORTS: set[int] = set()


class MetricsServer:
    """Prometheus HTTP metrics endpoint.

    A fixed-port metrics endpoint is process-global: the first gateway in the
    process binds the port and later instances reuse it instead of failing with
    EADDRINUSE (which is what happens on Linux when a second gateway tries to
    bind the same port while the first listener is still active).
    """

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
        if self.port in _BOUND_PORTS:
            logger.info("Prometheus metrics server already running on port {}", self.port)
            self._started = True
            return
        start_http_server(self.port)
        _BOUND_PORTS.add(self.port)
        self._started = True
        logger.info("Prometheus metrics server started on port {}", self.port)

    async def stop(self) -> None:
        self._started = False

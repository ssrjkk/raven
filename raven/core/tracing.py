from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Generator

from loguru import logger

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


class _NoopTracer:
    def start_span(self, name: str, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan(name)

    def start_as_current_span(self, name: str, **kwargs: Any) -> Generator[_NoopSpan, None, None]:
        yield _NoopSpan(name)


class _NoopSpan:
    def __init__(self, name: str):
        self._name = name

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


def setup_tracing(
    service_name: str = "raven",
    enable_console: bool = True,
    endpoint: str | None = None,
) -> None:
    if not HAS_OTEL:
        logger.warning("OpenTelemetry not installed. Install: pip install raven-agent[tracing]")
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if enable_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except ImportError:
            logger.warning("OTLP exporter not installed. Install: opentelemetry-exporter-otlp-proto-http")
    otel_trace.set_tracer_provider(provider)
    logger.info("OpenTelemetry tracing initialized (service={})", service_name)


def get_tracer(name: str = "raven"):
    if HAS_OTEL:
        return otel_trace.get_tracer(name)
    return _NoopTracer()


@contextmanager
def trace_llm_call(model: str, **attributes: Any) -> Generator[Any, None, None]:
    tracer = get_tracer("raven.llm")
    span_name = f"llm.{model}"
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("llm.model", model)
        for k, v in attributes.items():
            span.set_attribute(k, str(v))
        start = time.monotonic()
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error", str(exc))
            raise
        finally:
            duration = time.monotonic() - start
            span.set_attribute("llm.duration_ms", round(duration * 1000, 1))


def trace_tool_call(tool_name: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        name = tool_name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer("raven.tool")
            span_name = f"tool.{name}"
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("tool.name", name)
                start = time.monotonic()
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as exc:
                    span.set_attribute("error", str(exc))
                    raise
                finally:
                    duration = time.monotonic() - start
                    span.set_attribute("tool.duration_ms", round(duration * 1000, 1))

        return async_wrapper

    return decorator


tracer = get_tracer()

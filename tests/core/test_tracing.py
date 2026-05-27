from __future__ import annotations

import pytest

from raven.core.tracing import (
    HAS_OTEL,
    _NoopSpan,
    _NoopTracer,
    get_tracer,
    trace_llm_call,
    trace_tool_call,
    setup_tracing,
)


def test_noop_tracer():
    t = _NoopTracer()
    span = t.start_span("test")
    assert isinstance(span, _NoopSpan)


def test_noop_span():
    s = _NoopSpan("test")
    s.set_attribute("key", "val")
    s.set_status("ok")
    s.end()
    with s as ctx:
        assert ctx is s


def test_get_tracer_returns_tracer():
    t = get_tracer("test")
    span = t.start_span("x")
    assert hasattr(span, "set_attribute")
    assert hasattr(span, "end")


def test_trace_llm_call_context():
    with trace_llm_call("gpt-4", prompt="hello") as span:
        assert span is not None
        span.set_attribute("test", "value")


def test_trace_llm_call_exception():
    try:
        with trace_llm_call("test-model"):
            raise ValueError("oops")
    except ValueError:
        pass


async def _dummy_tool(x: int) -> int:
    return x * 2


@pytest.mark.asyncio
async def test_trace_tool_call_decorator():
    decorated = trace_tool_call("dummy")(_dummy_tool)
    result = await decorated(5)
    assert result == 10


@pytest.mark.asyncio
async def test_trace_tool_call_exception():
    async def _failing():
        raise RuntimeError("fail")

    decorated = trace_tool_call("failing")(_failing)
    with pytest.raises(RuntimeError):
        await decorated()


@pytest.mark.asyncio
async def test_trace_tool_call_default_name():
    decorated = trace_tool_call()(_dummy_tool)
    result = await decorated(3)
    assert result == 6


def test_setup_tracing_no_otel():
    setup_tracing(service_name="test", enable_console=False)
    assert True


def test_has_otel_attribute():
    assert HAS_OTEL in (True, False)

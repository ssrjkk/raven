from __future__ import annotations

import pytest

from raven.core.tracing import (
    _NoopSpan,
    _NoopTracer,
    get_tracer,
    trace_llm_call,
    trace_tool_call,
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


def test_trace_llm_call_exception(monkeypatch):
    """A failed call must be recorded on the span AND still raise: swallowing it here would hide
    every LLM error from the caller, and the old try/except-pass version checked neither."""
    from contextlib import contextmanager

    import raven.core.tracing as tracing

    attrs: dict[str, object] = {}
    names: list[str] = []

    class _Span:
        def set_attribute(self, key: str, value: object) -> None:
            attrs[key] = value

    class _Tracer:
        @contextmanager
        def start_as_current_span(self, name: str):
            names.append(name)
            yield _Span()

    monkeypatch.setattr(tracing, "get_tracer", lambda _name: _Tracer())

    with pytest.raises(ValueError, match="oops"):
        with tracing.trace_llm_call("test-model"):
            raise ValueError("oops")

    assert names == ["llm.test-model"]
    assert attrs["llm.model"] == "test-model"
    assert attrs["error"] == "oops"
    assert "llm.duration_ms" in attrs, "the finally block must still time a failed call"


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

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.core.circuit_breaker import CircuitBreakerOpenError
from raven.core.failover import ModelConfig, ModelFailover
from raven.core.llm.protocol import ToolCall


class FakeLLM:
    def __init__(self):
        self.complete_calls = []
        self.results = {}
        self.stream_results: dict[str, list[str]] = {}

    async def complete(self, messages, model=None, tools=None):
        self.complete_calls.append({"model": model, "tools": tools})
        result = self.results.get(model)
        if isinstance(result, Exception):
            raise result
        return result

    async def complete_stream(self, messages, model=None, tools=None):
        self.complete_calls.append({"model": model, "tools": tools})
        result = self.results.get(model)
        if isinstance(result, Exception):
            raise result
        for token in self.stream_results.get(model, []):
            yield token


class FakeResponse:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


@pytest.mark.asyncio
async def test_model_config():
    mc = ModelConfig("openai", "gpt-4", weight=2.0)
    assert mc.provider == "openai"
    assert mc.model == "gpt-4"
    assert mc.weight == 2.0


@pytest.mark.asyncio
async def test_model_config_default_weight():
    mc = ModelConfig("ollama", "llama3")
    assert mc.weight == 1.0


@pytest.mark.asyncio
async def test_failover_complete_empty_models():
    llm = FakeLLM()
    f = ModelFailover(llm)
    f._models = []
    with pytest.raises(RuntimeError, match="All models exhausted"):
        await f.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_failover_fallback_on_error():
    llm = FakeLLM()
    llm.results = {
        "model-a": RuntimeError("fail"),
        "model-b": FakeResponse(content="ok"),
    }
    f = ModelFailover(llm)
    f._models = [
        ModelConfig("p1", "model-a"),
        ModelConfig("p2", "model-b"),
    ]
    resp = await f.complete([{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert len(llm.complete_calls) == 2


@pytest.mark.asyncio
async def test_failover_all_fail():
    llm = FakeLLM()
    llm.results = {
        "a": RuntimeError("err1"),
        "b": RuntimeError("err2"),
    }
    f = ModelFailover(llm)
    f._models = [
        ModelConfig("p1", "a"),
        ModelConfig("p2", "b"),
    ]
    with pytest.raises(RuntimeError):
        await f.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_failover_complete_empty_response():
    llm = FakeLLM()
    llm.results = {
        "m": FakeResponse(content="", tool_calls=[]),
    }
    f = ModelFailover(llm)
    f._models = [ModelConfig("p", "m")]
    with pytest.raises(RuntimeError, match="All models exhausted"):
        await f.complete([{"role": "user", "content": "hi"}])


def test_failover_pick_random():
    llm = FakeLLM()
    f = ModelFailover(llm)
    f._models = [ModelConfig("p1", "a", 1.0), ModelConfig("p2", "b", 1.0)]
    mc = f.pick_random()
    assert mc.model in ("a", "b")


def test_failover_pick_random_empty():
    llm = FakeLLM()
    f = ModelFailover(llm)
    f._models = []
    with pytest.raises(RuntimeError, match="No models configured"):
        f.pick_random()


class TestGetCircuit:
    def test_creates_circuit_per_provider(self):
        llm = FakeLLM()
        f = ModelFailover(llm)
        c1 = f._get_circuit("openai")
        c2 = f._get_circuit("openai")
        assert c1 is c2
        c3 = f._get_circuit("anthropic")
        assert c3 is not c1

    def test_circuit_has_correct_config(self):
        llm = FakeLLM()
        f = ModelFailover(llm)
        cb = f._get_circuit("test")
        assert cb.name == "test"
        assert cb._failure_threshold == 3


class TestCompleteWithCircuitBreaker:
    async def test_skips_open_circuit(self):
        llm = FakeLLM()
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        cb = f._get_circuit("p1")
        cb._state = "open"
        cb._last_failure_time = 999999999.0
        llm.results = {"b": FakeResponse(content="ok")}
        resp = await f.complete([{"role": "user", "content": "hi"}])
        assert resp.content == "ok"
        assert len(llm.complete_calls) == 1
        assert llm.complete_calls[0]["model"] == "b"


class TestCompleteStream:
    async def test_stream_success_first_model(self):
        llm = FakeLLM()
        llm.stream_results = {"a": ["hello", " ", "world"]}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a")]
        tokens = []
        async for token in f.complete_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        assert tokens == ["hello", " ", "world"]

    async def test_stream_fallback_on_error(self):
        llm = FakeLLM()
        llm.results = {"a": RuntimeError("fail")}
        llm.stream_results = {"b": ["recovered"]}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        tokens = []
        async for token in f.complete_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        assert tokens == ["recovered"]

    async def test_stream_all_fail(self):
        llm = FakeLLM()
        llm.results = {"a": RuntimeError("err1"), "b": RuntimeError("err2")}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        with pytest.raises(RuntimeError):
            async for _ in f.complete_stream([{"role": "user", "content": "hi"}]):
                pass

    async def test_stream_skips_open_circuit(self):
        llm = FakeLLM()
        llm.stream_results = {"b": ["ok"]}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        cb = f._get_circuit("p1")
        cb._state = "open"
        cb._last_failure_time = 999999999.0
        tokens = []
        async for token in f.complete_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        assert tokens == ["ok"]

    async def test_stream_empty_models_raises(self):
        llm = FakeLLM()
        f = ModelFailover(llm)
        f._models = []
        with pytest.raises(RuntimeError, match="All models exhausted"):
            async for _ in f.complete_stream([{"role": "user", "content": "hi"}]):
                pass

    async def test_stream_failure_calls_cb_on_failure(self):
        llm = FakeLLM()
        llm.results = {"a": RuntimeError("fail")}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a")]
        with pytest.raises(RuntimeError):
            async for _ in f.complete_stream([{"role": "user", "content": "hi"}]):
                pass
        cb = f._get_circuit("p1")
        assert cb._failure_count >= 1

    async def test_stream_success_calls_cb_on_success(self):
        llm = FakeLLM()
        llm.stream_results = {"a": ["ok"]}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a")]
        async for _ in f.complete_stream([{"role": "user", "content": "hi"}]):
            pass
        cb = f._get_circuit("p1")
        assert cb._metrics["successes"] >= 1

    async def test_stream_skips_empty_first_model(self):
        llm = FakeLLM()
        llm.stream_results = {"a": [], "b": ["recovered"]}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        tokens = []
        async for token in f.complete_stream([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        assert tokens == ["recovered"]
        assert [c["model"] for c in llm.complete_calls] == ["a", "b"]

    async def test_stream_all_empty_raises(self):
        llm = FakeLLM()
        llm.stream_results = {"a": [], "b": []}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a"), ModelConfig("p2", "b")]
        with pytest.raises(RuntimeError, match="All models exhausted"):
            async for _ in f.complete_stream([{"role": "user", "content": "hi"}]):
                pass


class TestCompleteWithToolCalls:
    async def test_tool_calls_returned(self):
        llm = FakeLLM()
        llm.results = {"a": FakeResponse(content="", tool_calls=[ToolCall(id="t1", name="test", arguments={})])}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a")]
        resp = await f.complete([{"role": "user", "content": "hi"}])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "test"

    async def test_tools_passed_through(self):
        llm = FakeLLM()
        llm.results = {"a": FakeResponse(content="ok")}
        f = ModelFailover(llm)
        f._models = [ModelConfig("p1", "a")]
        tools = [{"type": "function", "function": {"name": "test"}}]
        await f.complete([{"role": "user", "content": "hi"}], tools=tools)
        assert llm.complete_calls[0]["tools"] == tools

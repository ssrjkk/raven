from __future__ import annotations

import pytest

from raven.core.failover import ModelConfig, ModelFailover


class FakeLLM:
    def __init__(self):
        self.complete_calls = []
        self.results = {}

    async def complete(self, messages, model=None, tools=None):
        self.complete_calls.append({"model": model, "tools": tools})
        result = self.results.get(model)
        if isinstance(result, Exception):
            raise result
        return result


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
    f = ModelFailover(llm)  # type: ignore[arg-type]
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
    f = ModelFailover(llm)  # type: ignore[arg-type]
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
    f = ModelFailover(llm)  # type: ignore[arg-type]
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
    f = ModelFailover(llm)  # type: ignore[arg-type]
    f._models = [ModelConfig("p", "m")]
    with pytest.raises(RuntimeError, match="All models exhausted"):
        await f.complete([{"role": "user", "content": "hi"}])


def test_failover_pick_random():
    llm = FakeLLM()
    f = ModelFailover(llm)  # type: ignore[arg-type]
    f._models = [ModelConfig("p1", "a", 1.0), ModelConfig("p2", "b", 1.0)]
    mc = f.pick_random()
    assert mc.model in ("a", "b")


def test_failover_pick_random_empty():
    llm = FakeLLM()
    f = ModelFailover(llm)  # type: ignore[arg-type]
    f._models = []
    with pytest.raises(RuntimeError, match="No models configured"):
        f.pick_random()

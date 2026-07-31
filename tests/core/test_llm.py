from __future__ import annotations

import json
from typing import ClassVar

import pytest

from raven.core.llm import LLMProvider, LLMResponse, LLMRouter, ToolCall


class _AllKeysDiscovery:
    providers_available: ClassVar[list[str]] = [
        "ollama",
        "openai",
        "anthropic",
        "openrouter",
        "groq",
        "vertex",
        "bedrock",
        "copilot",
    ]

    def is_available(self, key_name: str) -> bool:
        return True


@pytest.fixture
def all_keys(monkeypatch):
    import raven.core.config_discovery as discovery

    monkeypatch.setattr(discovery, "get_discovered_keys", lambda *a, **k: _AllKeysDiscovery())
    return discovery


class TestToolCall:
    def test_create(self):
        tc = ToolCall(id="call_1", name="test_tool", arguments={"x": 1})
        assert tc.id == "call_1"
        assert tc.name == "test_tool"
        assert tc.arguments == {"x": 1}

    def test_to_dict(self):
        tc = ToolCall(id="call_1", name="test_tool", arguments={"x": 1})
        d = tc.to_dict()
        assert d["id"] == "call_1"
        assert d["type"] == "function"
        assert d["function"]["name"] == "test_tool"
        assert json.loads(d["function"]["arguments"]) == {"x": 1}

    def test_from_openai(self):
        raw = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"x": 1}'},
        }
        tc = ToolCall.from_openai(raw)
        assert tc.id == "call_1"
        assert tc.name == "test_tool"
        assert tc.arguments == {"x": 1}

    def test_from_openai_dict_args(self):
        raw = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": {"x": 1}},
        }
        tc = ToolCall.from_openai(raw)
        assert tc.arguments == {"x": 1}


class TestLLMResponse:
    def test_defaults(self):
        resp = LLMResponse()
        assert resp.content == ""
        assert resp.tool_calls == []
        assert resp.finish_reason == "stop"

    def test_with_content(self):
        resp = LLMResponse(content="hello")
        assert resp.content == "hello"

    def test_with_tool_calls(self):
        tc = ToolCall(id="c1", name="t", arguments={})
        resp = LLMResponse(tool_calls=[tc])
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "t"


class TestLLMRouter:
    def _unwrapped(self, prov: LLMProvider) -> type[LLMProvider]:
        from raven.core.metrics import InstrumentedLLMProvider
        if isinstance(prov, InstrumentedLLMProvider):
            return type(prov._wrapped)
        return type(prov)

    def test_get_provider_openrouter(self, all_keys):
        router = LLMRouter()
        prov = router._get_provider("openrouter/anthropic/claude-3")
        assert self._unwrapped(prov).__name__ == "OpenRouterProvider"

    def test_get_provider_anthropic(self, all_keys):
        router = LLMRouter()
        prov = router._get_provider("claude-3-haiku-20240307")
        assert self._unwrapped(prov).__name__ == "AnthropicProvider"

    def test_get_provider_openai(self, all_keys):
        router = LLMRouter()
        prov = router._get_provider("gpt-4o")
        assert self._unwrapped(prov).__name__ == "OpenAIProvider"

    def test_get_provider_ollama(self):
        router = LLMRouter()
        prov = router._get_provider("ollama/llama3")
        assert self._unwrapped(prov).__name__ == "OllamaProvider"

    def test_get_provider_fallback(self):
        router = LLMRouter()
        prov = router._get_provider("unknown/model")
        assert self._unwrapped(prov).__name__ == "OllamaProvider"

    def test_get_provider_empty_default(self):
        router = LLMRouter()
        prov = router._get_provider("")
        assert prov is not None

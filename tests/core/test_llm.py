from __future__ import annotations

import json
from typing import Any, ClassVar

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


class _OnlyLocalDiscovery:
    providers_available: ClassVar[list[str]] = ["ollama"]

    def is_available(self, key_name: str) -> bool:
        return key_name == "OLLAMA_BASE_URL"


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
        from raven.core.instrumented import InstrumentedLLMProvider

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

    def test_an_empty_model_resolves_the_configured_default(self, all_keys, monkeypatch):
        """`DEFAULT_MODEL` has to be what an empty model gets, and it has to resolve.

        This asserted only `is not None` against whatever the machine running the suite had in its
        `.env`, so a `DEFAULT_MODEL` naming a provider with no key made it raise: a property of the
        install, not of the router.
        """
        from raven.core.config import settings

        monkeypatch.setattr(settings, "default_model", "gpt-4o")
        prov = LLMRouter()._get_provider("")
        assert self._unwrapped(prov).__name__ == "OpenAIProvider"

    def test_a_default_naming_a_provider_without_a_key_is_refused_loudly(self, monkeypatch):
        from raven.core import config_discovery
        from raven.core.config import settings

        monkeypatch.setattr(settings, "default_model", "gpt-4o")
        monkeypatch.setattr(config_discovery, "get_discovered_keys", lambda *a, **k: _OnlyLocalDiscovery())
        with pytest.raises(RuntimeError, match="requires OPENAI_API_KEY which is not set"):
            LLMRouter()._get_provider("")


class TestAnthropicPromptCaching:
    def _provider(self) -> Any:
        from raven.core.llm.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key="test-key")

    @pytest.mark.asyncio
    async def test_system_block_gets_cache_control(self):
        prov = self._provider()
        body = prov._build_body(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            "claude-3-haiku-20240307",
            stream=False,
        )
        assert isinstance(body["system"], list)
        assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        await prov.cleanup()

    @pytest.mark.asyncio
    async def test_caching_can_be_disabled(self):
        from raven.core.llm.providers.anthropic import AnthropicProvider

        prov = AnthropicProvider(api_key="test-key", prompt_caching=False)
        body = prov._build_body(
            [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
            "claude-3-haiku-20240307",
            stream=False,
        )
        assert body["system"] == "sys"
        await prov.cleanup()

    @pytest.mark.asyncio
    async def test_no_system_message_omits_field(self):
        prov = self._provider()
        body = prov._build_body([{"role": "user", "content": "hi"}], "claude-3-haiku-20240307", stream=False)
        assert "system" not in body
        await prov.cleanup()

from __future__ import annotations
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any
import httpx
from loguru import logger
from raven.core.config import settings


class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def __init__(self, id: str, name: str, arguments: dict[str, Any]):
        self.id = id
        self.name = name
        self.arguments = arguments

    def to_dict(self) -> dict:
        return {"id": self.id, "type": "function", "function": {"name": self.name, "arguments": json.dumps(self.arguments)}}

    @classmethod
    def from_openai(cls, tc: dict) -> "ToolCall":
        args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
        return cls(id=tc["id"], name=tc["function"]["name"], arguments=args)


class LLMResponse:
    def __init__(self, content: str = "", tool_calls: list[ToolCall] | None = None, finish_reason: str = "stop"):
        self.content = content
        self.tool_calls = tool_calls or []
        self.finish_reason = finish_reason


class LLMProvider(ABC):
    @abstractmethod
    async def complete_stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        ...


class OpenRouterProvider(LLMProvider):
    def __init__(self):
        self.api_key = settings.openrouter_api_key
        self.base_url = "https://openrouter.ai/api/v1"
        self.http = httpx.AsyncClient(timeout=120)

    async def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/raven-ai",
            "X-Title": "Raven AI",
        }

    async def complete_stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        body = {"model": model.replace("openrouter/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async with self.http.stream("POST", f"{self.base_url}/chat/completions", json=body, headers=await self._headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        model_name = model.replace("openrouter/", "")
        body = {"model": model_name, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(f"{self.base_url}/chat/completions", json=body, headers=await self._headers())
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content", "") or ""
        tool_calls_raw = msg.get("tool_calls")
        tool_calls = [ToolCall.from_openai(tc) for tc in tool_calls_raw] if tool_calls_raw else []
        finish = choice.get("finish_reason", "stop")
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)


class OpenAIProvider(LLMProvider):
    def __init__(self):
        self.api_key = settings.openai_api_key
        self.http = httpx.AsyncClient(timeout=120)

    async def complete_stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        body = {"model": model, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async with self.http.stream("POST", "https://api.openai.com/v1/chat/completions", json=body, headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        }) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        body = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post("https://api.openai.com/v1/chat/completions", json=body, headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
        })
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        content = msg.get("content", "") or ""
        tool_calls_raw = msg.get("tool_calls")
        tool_calls = [ToolCall.from_openai(tc) for tc in tool_calls_raw] if tool_calls_raw else []
        finish = choice.get("finish_reason", "stop")
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=finish)


class AnthropicProvider(LLMProvider):
    def __init__(self):
        self.api_key = settings.anthropic_api_key
        self.http = httpx.AsyncClient(timeout=120)

    async def complete_stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        body = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "system": next((m["content"] for m in messages if m["role"] == "system"), ""),
            "max_tokens": 4096,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        async with self.http.stream("POST", "https://api.anthropic.com/v1/messages", json=body, headers={
            "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json",
        }) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    try:
                        chunk = json.loads(data)
                        if chunk.get("type") == "content_block_delta":
                            text = chunk.get("delta", {}).get("text", "")
                            if text:
                                yield text
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        body = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "system": next((m["content"] for m in messages if m["role"] == "system"), ""),
            "max_tokens": 4096,
        }
        if tools:
            body["tools"] = tools
        resp = await self.http.post("https://api.anthropic.com/v1/messages", json=body, headers={
            "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json",
        })
        resp.raise_for_status()
        data = resp.json()
        content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return LLMResponse(content=content, finish_reason="stop")


class OllamaProvider(LLMProvider):
    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.http = httpx.AsyncClient(timeout=120)

    async def complete_stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        model_name = model.replace("ollama/", "")
        body = {"model": model_name, "messages": messages, "stream": True}
        async with self.http.stream("POST", f"{self.base_url}/api/chat", json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    async def complete(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        model_name = model.replace("ollama/", "")
        body = {"model": model_name, "messages": messages, "stream": False}
        resp = await self.http.post(f"{self.base_url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(content=data.get("message", {}).get("content", ""), finish_reason="stop")


class LLMRouter:
    def __init__(self):
        self._providers: dict[str, LLMProvider] = {}

    def _get_provider(self, model: str) -> LLMProvider:
        if not model:
            model = settings.default_model
        if model.startswith("openrouter/"):
            key = "openrouter"
        elif model.startswith("claude") or model.startswith("anthropic/"):
            key = "anthropic"
        elif model.startswith("ollama/"):
            key = "ollama"
        elif model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
            key = "openai"
        else:
            key = "openrouter"
        if key not in self._providers:
            if key == "openrouter":
                self._providers[key] = OpenRouterProvider()
            elif key == "anthropic":
                self._providers[key] = AnthropicProvider()
            elif key == "ollama":
                self._providers[key] = OllamaProvider()
            elif key == "openai":
                self._providers[key] = OpenAIProvider()
        return self._providers[key]

    async def complete_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        model = model or settings.default_model
        provider = self._get_provider(model)
        async for token in provider.complete_stream(messages, model, tools):
            yield token

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        model = model or settings.default_model
        provider = self._get_provider(model)
        return await provider.complete(messages, model, tools)

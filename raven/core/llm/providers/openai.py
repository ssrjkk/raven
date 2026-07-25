from __future__ import annotations

import os
from typing import Any

from pydantic import SecretStr

from raven.core.config import settings
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.providers.base import (
    _parse_openai_response,
    _stream_sse,
)


class OpenRouterProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.openrouter_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://openrouter.ai/api/v1"
        self.http = self._build_http_client(overrides)

    @staticmethod
    def _build_http_client(overrides: dict[str, Any]):
        import httpx

        return httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def _headers(self) -> dict[str, Any]:
        return {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/raven-ai",
            "X-Title": "Raven AI",
        }

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        body = {"model": model.replace("openrouter/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(self.http, f"{self.base_url}/chat/completions", body, await self._headers()):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model_name = model.replace("openrouter/", "")
        body = {"model": model_name, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(f"{self.base_url}/chat/completions", json=body, headers=await self._headers())
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class OpenAIProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.openai_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://api.openai.com/v1"
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        body = {"model": model, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(
            self.http,
            f"{self.base_url}/chat/completions",
            body,
            {
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        ):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={
                "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class VLLMProvider(LLMProvider):
    def __init__(self, **overrides):
        self.base_url = overrides.get("base_url") or settings.vllm_base_url
        raw = overrides.get("api_key") or ""
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        body = {"model": model.replace("vllm/", ""), "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        async for token in _stream_sse(self.http, f"{self.base_url}/v1/chat/completions", body, headers):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = {"model": model.replace("vllm/", ""), "messages": messages}
        if tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        resp = await self.http.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())


class AzureProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.endpoint = overrides.get("base_url") or os.environ.get(
            "AZURE_OPENAI_ENDPOINT", "https://your-resource.openai.azure.com"
        )
        self.api_version = overrides.get("api_version") or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    def _deployment(self, model: str) -> str:
        return model.replace("azure/", "")

    def _url(self, deployment: str) -> str:
        return f"{self.endpoint}/openai/deployments/{deployment}/chat/completions?api-version={self.api_version}"

    async def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "api-key": self.api_key.get_secret_value()}

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        deployment = self._deployment(model)
        body = {"messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        async for token in _stream_sse(self.http, self._url(deployment), body, await self._headers()):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        deployment = self._deployment(model)
        body = {"messages": messages}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(self._url(deployment), json=body, headers=await self._headers())
        resp.raise_for_status()
        return _parse_openai_response(resp.json())

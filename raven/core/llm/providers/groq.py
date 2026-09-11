from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from raven.core.config import settings
from raven.core.llm.protocol import LLMProvider, LLMResponse
from raven.core.llm.providers.base import (
    _parse_openai_response,
    _stream_sse,
)

FREE_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "groq/compound",
    "groq/compound-mini",
]


class GroqProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.groq_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://api.groq.com/openai/v1"
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
        body = {"model": model.replace("groq/", ""), "messages": messages, "stream": True}
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
        body = {"model": model.replace("groq/", ""), "messages": messages}
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

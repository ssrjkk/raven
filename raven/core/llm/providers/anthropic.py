from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from raven.core.config import settings
from raven.core.llm.protocol import LLMProvider, LLMResponse, ToolCall
from raven.core.llm.providers.base import _stream_sse


class AnthropicProvider(LLMProvider):
    def __init__(self, **overrides):
        raw = overrides.get("api_key") or settings.anthropic_api_key.get_secret_value()
        self.api_key = SecretStr(raw) if isinstance(raw, str) else raw
        self.base_url = overrides.get("base_url") or "https://api.anthropic.com"
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self.api_key = SecretStr("")

    def _build_body(
        self, messages: list[dict[str, Any]], model: str, stream: bool, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body = {
            "model": model,
            "messages": [m for m in messages if m["role"] != "system"],
            "system": "\n\n".join(m["content"] for m in messages if m["role"] == "system"),
            "max_tokens": 4096,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
        return body

    def _headers(self) -> dict[str, Any]:
        return {
            "x-api-key": self.api_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
        body = self._build_body(messages, model, True, tools)
        async for token in _stream_sse(
            self.http,
            f"{self.base_url}/v1/messages",
            body,
            self._headers(),
            done_marker="",
            extract_token=lambda c: (
                c.get("delta", {}).get("text", "") if c.get("type") == "content_block_delta" else ""
            ),
        ):
            yield token

    async def complete(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        body = self._build_body(messages, model, False, tools)
        resp = await self.http.post(f"{self.base_url}/v1/messages", json=body, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        tool_calls_raw = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
        tool_calls = [
            ToolCall(id=tc.get("id", ""), name=tc.get("name", ""), arguments=tc.get("input", {}))
            for tc in tool_calls_raw
        ]
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason="stop")

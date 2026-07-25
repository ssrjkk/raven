from __future__ import annotations

from typing import Any

from raven.core._json import json
from raven.core.config import settings
from raven.core.llm.protocol import LLMProvider, LLMResponse, ToolCall


class OllamaProvider(LLMProvider):
    def __init__(self, **overrides):
        self.base_url = overrides.get("base_url") or settings.ollama_base_url
        import httpx

        self.http = httpx.AsyncClient(
            timeout=overrides.get("timeout", 120),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()

    async def complete_stream(
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> Any:
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
        self, messages: list[dict[str, Any]], model: str, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        model_name = model.replace("ollama/", "")
        body = {"model": model_name, "messages": messages, "stream": False}
        if tools:
            body["tools"] = tools
        resp = await self.http.post(f"{self.base_url}/api/chat", json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        tool_calls_raw = data.get("message", {}).get("tool_calls", [])
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=tc.get("function", tc).get("name", ""),
                arguments=tc.get("function", tc).get("arguments", {}),
            )
            for tc in tool_calls_raw
        ]
        usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        }
        return LLMResponse(content=content, tool_calls=tool_calls, finish_reason="stop", usage=usage)

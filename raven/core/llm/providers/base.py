from __future__ import annotations

import email.utils
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import SecretStr

from raven.core._json import json
from raven.core.llm.protocol import LLMResponse, ToolCall


def _parse_retry_after(headers: Any, default: int = 5) -> int:
    raw = headers.get("Retry-After")
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        if parsed is None:
            return default
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(int(parsed.timestamp() - time.time()), 0)
    except (ValueError, TypeError):
        return default


def _read_json_file(path: str) -> dict[str, Any]:
    with Path(path).open() as f:
        import json as _json

        return cast("dict[str, Any]", _json.load(f))


async def _stream_sse(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, Any],
    done_marker: str = "[DONE]",
    data_prefix: str = "data: ",
    extract_token: Callable[[dict[str, Any]], str] = lambda c: (
        c.get("choices", [{}])[0].get("delta", {}).get("content", "")
    ),
) -> AsyncIterator[str]:
    async with client.stream("POST", url, json=body, headers=headers) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith(data_prefix):
                data = line[len(data_prefix) :]
                if data.strip() == done_marker:
                    break
                try:
                    chunk = json.loads(data)
                    token = extract_token(chunk)
                    if token:
                        yield token
                except json.JSONDecodeError:
                    continue


def _parse_openai_response(data: dict[str, Any]) -> LLMResponse:
    choice = data.get("choices", [{}])[0] if data.get("choices") else {}
    msg = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = msg.get("content", "") or ""
    tool_calls_raw = msg.get("tool_calls")
    tool_calls = [ToolCall.from_openai(tc) for tc in tool_calls_raw] if tool_calls_raw else []
    usage_raw = data.get("usage", {})
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens", 0),
        "completion_tokens": usage_raw.get("completion_tokens", 0),
        "total_tokens": usage_raw.get("total_tokens", 0),
    } if usage_raw else {}
    return LLMResponse(content=content, tool_calls=tool_calls, finish_reason=choice.get("finish_reason", "stop"), usage=usage)


def _convert_to_gemini(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            continue
        parts = [{"text": content}]
        gemini_role = "user" if role in ("user", "tool") else "model"
        contents.append({"role": gemini_role, "parts": parts})
    return contents


def _convert_to_bedrock_converse(messages: list[dict[str, Any]]) -> dict[str, Any]:
    converted = []
    system_text = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_text += content + "\n"
            continue
        bedrock_role = "assistant" if role == "assistant" else "user"
        converted.append({"role": bedrock_role, "content": [{"text": content}]})
    body: dict[str, Any] = {"messages": converted}
    if system_text:
        body["system"] = [{"text": system_text.strip()}]
    return body


class BaseLLMProvider:
    def __init__(self, api_key: SecretStr | str, base_url: str, timeout: float = 120.0):
        self._api_key = SecretStr(api_key) if isinstance(api_key, str) else api_key
        self.http = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
        )

    async def cleanup(self):
        await self.http.aclose()
        self._api_key = SecretStr("")

    def _get_api_key(self) -> str:
        return self._api_key.get_secret_value()

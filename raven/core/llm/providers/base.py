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


def _openai_chunk_to_events(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one OpenAI-style SSE chunk into typed delta events.

    Event shapes:
      {"type": "token", "text": str}
      {"type": "tool_call", "index": int, "id": str, "name": str, "args_fragment": str}
    (id/name/args_fragment are optional per event; fragments must be concatenated
    in arrival order per index.)
    """
    events: list[dict[str, Any]] = []
    choices = chunk.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta") or {}
    content = delta.get("content")
    if content:
        events.append({"type": "token", "text": content})
    for tc in delta.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        ev: dict[str, Any] = {"type": "tool_call", "index": tc.get("index", 0)}
        if tc.get("id"):
            ev["id"] = tc["id"]
        if fn.get("name"):
            ev["name"] = fn["name"]
        if fn.get("arguments"):
            ev["args_fragment"] = fn["arguments"]
        if len(ev) > 2:  # beyond type+index there is actual payload
            events.append(ev)
    return events


async def _stream_sse_deltas(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, Any],
    done_marker: str = "[DONE]",
    data_prefix: str = "data: ",
) -> AsyncIterator[dict[str, Any]]:
    """Stream an OpenAI-compatible SSE endpoint as typed delta events (tokens + tool calls)."""
    async with client.stream("POST", url, json=body, headers=headers) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith(data_prefix):
                data = line[len(data_prefix) :]
                if data.strip() == done_marker:
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for ev in _openai_chunk_to_events(chunk):
                    yield ev


async def collect_stream_deltas(events: AsyncIterator[dict[str, Any]]) -> tuple[str, list[ToolCall]]:
    """Assemble typed delta events into (content, tool_calls)."""
    content_parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    async for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "token":
            content_parts.append(str(ev.get("text", "")))
        elif etype == "tool_call":
            idx = ev.get("index", 0)
            entry = calls.get(idx)
            if entry is None:
                entry = {"id": "", "name": "", "args": []}
                calls[idx] = entry
                order.append(idx)
            if ev.get("id"):
                entry["id"] = ev["id"]
            if ev.get("name"):
                entry["name"] = ev["name"]
            if ev.get("args_fragment"):
                entry["args"].append(ev["args_fragment"])
    content = "".join(content_parts)
    tool_calls: list[ToolCall] = []
    for idx in order:
        entry = calls[idx]
        raw_args = "".join(entry["args"]).strip() or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
        if not isinstance(args, dict):
            args = {"_raw": str(args)}
        tool_calls.append(ToolCall(id=entry["id"] or f"call_{idx}", name=entry["name"], arguments=args))
    return content, tool_calls


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

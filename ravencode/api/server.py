"""OpenAI-совместимый API сервер — drop-in replacement OpenAI API."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.tools import get_tool_definitions


class ChatMessage(BaseModel):
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "ravencode"
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 4096
    temperature: float = 0.7


class DeltaMessage(BaseModel):
    role: str | None = None
    content: str | None = None


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatMessage | None = None
    delta: DeltaMessage | None = None
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = "ravencode"
    choices: list[ChatChoice] = []
    usage: Usage | None = None


_API_KEY = os.environ.get("RAVENCODE_API_KEY", "")


def _check_auth(authorization: str = "") -> None:
    if not _API_KEY:
        return
    key = authorization
    if key.startswith("Bearer "):
        key = key[7:]
    if key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


app = FastAPI(title="RavenCode API", version="0.4.0")


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + len(text.split())


def _to_openai_tool_defs() -> list[dict[str, Any]]:
    tools = get_tool_definitions()
    return [
        {
            "type": "function",
            "function": {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "parameters": t["function"]["parameters"],
            },
        }
        for t in tools
    ]


def _openai_messages_to_conversation(messages: list[ChatMessage]) -> Conversation:
    """Build the agent conversation from all but the last request message.

    The final message is replayed through ``agent.run()``; including it here
    as well would duplicate it in the model context. Prior assistant
    tool_calls and tool results are preserved so multi-turn tool flows stay
    protocol-valid.
    """
    conv = Conversation()
    conv.messages = [m.model_dump(exclude_none=True) for m in messages[:-1]]
    return conv


def _split_conversation_input(messages: list[ChatMessage]) -> tuple[Conversation, str]:
    if not messages:
        return Conversation(), ""
    last = messages[-1]
    if last.role == "user":
        return _openai_messages_to_conversation(messages), last.content or ""
    # A tool/assistant turn came last (multi-turn tool flow): keep the full
    # history intact and nudge the agent with a synthetic continuation.
    conv = Conversation()
    conv.messages = [m.model_dump(exclude_none=True) for m in messages]
    return conv, "Continue."


def _sse_chunk(chunk_id: str, model: str, delta: dict[str, Any], finish: str | None = None) -> str:
    return (
        f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]})}\n\n"
    )


async def _run_agent_nonstream(messages: list[ChatMessage], model: str, max_tokens: int) -> ChatCompletionResponse:
    conv, content = _split_conversation_input(messages)
    agent = ReActAgent(conversation=conv, max_steps=20)
    try:
        result = await agent.run(content)
    except Exception as exc:
        logger.error("Agent non-stream run failed: {}", exc)
        result = "Agent execution error"

    prompt_text = json.dumps([m.model_dump() for m in messages])
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[ChatChoice(message=ChatMessage(role="assistant", content=result), finish_reason="stop")],
        usage=Usage(
            prompt_tokens=_estimate_tokens(prompt_text),
            completion_tokens=_estimate_tokens(result),
            total_tokens=_estimate_tokens(prompt_text) + _estimate_tokens(result),
        ),
    )


async def _run_agent_stream(messages: list[ChatMessage], model: str) -> AsyncIterator[str]:
    conv, content = _split_conversation_input(messages)
    chunk_id = f"chatcmpl-{uuid4().hex[:12]}"

    emitter = EventEmitter()
    queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()

    async def _forward(ev: AgentEvent) -> None:
        if ev.type == "token":
            await queue.put(("token", str(ev.data.get("content", ""))))
        elif ev.type in ("tool_call", "tool_result"):
            payload = json.dumps({"event": ev.type, **ev.data}, default=str)
            await queue.put(("comment", payload))

    emitter.on("token", _forward)
    emitter.on("tool_call", _forward)
    emitter.on("tool_result", _forward)

    agent = ReActAgent(
        conversation=conv,
        max_steps=20,
        config=AgentConfig(event_emitter=emitter, stream_tokens=True, priority="high"),
    )

    async def _run() -> str:
        try:
            return await agent.run(content)
        except Exception as exc:
            logger.error("Agent stream run failed: {}", exc)
            return "Agent execution error"
        finally:
            await queue.put(None)

    task = asyncio.ensure_future(_run())

    yield _sse_chunk(chunk_id, model, {"role": "assistant"})

    streamed = 0
    while True:
        item = await queue.get()
        if item is None:
            break
        kind, payload = item
        if kind == "token":
            streamed += len(payload)
            yield _sse_chunk(chunk_id, model, {"content": payload})
        else:
            # SSE comment: invisible to OpenAI-compatible clients, great for debugging.
            yield f": {payload}\n\n"

    result = await task
    if streamed < len(result):
        rest = result[streamed:]
        for i in range(0, len(rest), 100):
            yield _sse_chunk(chunk_id, model, {"content": rest[i : i + 100]})
            await asyncio.sleep(0)

    yield _sse_chunk(chunk_id, model, {}, finish="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, authorization: str = "") -> Any:
    _check_auth(authorization)
    if request.stream:
        return StreamingResponse(
            _run_agent_stream(request.messages, request.model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    return await _run_agent_nonstream(request.messages, request.model, request.max_tokens)


@app.get("/v1/models")
async def list_models(authorization: str = "") -> dict[str, Any]:
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {"id": "ravencode", "object": "model", "created": int(time.time()), "owned_by": "raven"},
        ],
    }


def run_openai_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")

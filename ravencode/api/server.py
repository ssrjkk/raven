"""OpenAI-совместимый API сервер — drop-in replacement OpenAI API."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import json
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.context import Conversation
from ravencode.runtime.mcp_tools import ensure_mcp_tools
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
    # OpenAI protocol: max_tokens caps the completion; temperature is bounded, sampling stays provider-side.
    max_tokens: int = Field(default=4096, ge=1, le=200_000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


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
_BASIC_USERNAME = os.environ.get("RAVENCODE_SERVER_USERNAME", "ravencode")
_BASIC_PASSWORD = os.environ.get("RAVENCODE_SERVER_PASSWORD", "")

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS or host.startswith("127.")


def _basic_credentials(authorization: str) -> tuple[str, str] | None:
    if not authorization.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    username, sep, password = decoded.partition(":")
    return (username, password) if sep else None


def _check_auth(authorization: str = "") -> None:
    if not _API_KEY and not _BASIC_PASSWORD:
        return
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if _API_KEY and hmac.compare_digest(token, _API_KEY):
        return
    creds = _basic_credentials(authorization)
    if (
        _BASIC_PASSWORD
        and creds is not None
        and hmac.compare_digest(creds[0], _BASIC_USERNAME)
        and hmac.compare_digest(creds[1], _BASIC_PASSWORD)
    ):
        return
    raise HTTPException(status_code=401, detail="Invalid credentials")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        await ensure_mcp_tools()
    except Exception as exc:  # MCP is optional; never block the server
        logger.warning("MCP tools unavailable: {}", exc)
    yield


app = FastAPI(
    title="RavenCode API",
    version="0.4.8",
    description="OpenAI-compatible RavenCode API — by ssrjkk (https://github.com/ssrjkk).",
    contact={"name": "ssrjkk", "url": "https://github.com/ssrjkk"},
    license_info={"name": "MIT"},
    lifespan=lifespan,
)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + len(text.split())


_CHARS_PER_TOKEN = 4


def _truncate_to_budget(text: str, limit: int) -> tuple[str, bool]:
    """Cut text to the remaining char budget; True when the request's max_tokens ran out."""
    if len(text) <= limit:
        return text, False
    return text[: max(limit, 0)], True


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

    answer, capped = _truncate_to_budget(result, max_tokens * _CHARS_PER_TOKEN)
    prompt_text = json.dumps([m.model_dump() for m in messages])
    prompt_tokens = _estimate_tokens(prompt_text)
    completion_tokens = _estimate_tokens(answer)
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                message=ChatMessage(role="assistant", content=answer),
                finish_reason="length" if capped else "stop",
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _reap_agent_task(task: asyncio.Task[str]) -> None:
    """Consume a cancelled run's outcome so asyncio never reports it as an unretrieved exception."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        logger.debug("Agent stream task ended unobserved: {}", exc)


async def _run_agent_stream(messages: list[ChatMessage], model: str, max_tokens: int) -> AsyncGenerator[str, None]:
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
    task.add_done_callback(_reap_agent_task)
    budget = max_tokens * _CHARS_PER_TOKEN
    streamed = 0
    capped = False

    try:
        yield _sse_chunk(chunk_id, model, {"role": "assistant"})

        while not capped:
            item = await queue.get()
            if item is None:
                break
            kind, payload = item
            if kind != "token":
                # SSE comment: invisible to OpenAI-compatible clients, great for debugging.
                yield f": {payload}\n\n"
                continue
            piece, capped = _truncate_to_budget(payload, budget - streamed)
            streamed += len(piece)
            if piece:
                yield _sse_chunk(chunk_id, model, {"content": piece})

        if capped:
            # The client asked for max_tokens of text: stop the agent rather than burn the rest.
            task.cancel()
        else:
            result = await task
            rest, capped = _truncate_to_budget(result[streamed:], budget - streamed)
            for i in range(0, len(rest), 100):
                yield _sse_chunk(chunk_id, model, {"content": rest[i : i + 100]})
                await asyncio.sleep(0)

        yield _sse_chunk(chunk_id, model, {}, finish="length" if capped else "stop")
        yield "data: [DONE]\n\n"
    finally:
        if not task.done():
            # Client disconnected: without this the agent keeps calling the LLM and tools unobserved.
            task.cancel()


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, authorization: str = Header(default="")) -> Any:
    _check_auth(authorization)
    if request.stream:
        return StreamingResponse(
            _run_agent_stream(request.messages, request.model, request.max_tokens),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    return await _run_agent_nonstream(request.messages, request.model, request.max_tokens)


@app.get("/v1/models")
async def list_models(authorization: str = Header(default="")) -> dict[str, Any]:
    _check_auth(authorization)
    return {
        "object": "list",
        "data": [
            {"id": "ravencode", "object": "model", "created": int(time.time()), "owned_by": "raven"},
        ],
    }


def run_openai_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    username: str | None = None,
    password: str | None = None,
) -> None:
    import uvicorn

    global _BASIC_PASSWORD, _BASIC_USERNAME
    if username:
        _BASIC_USERNAME = username
    if password:
        _BASIC_PASSWORD = password

    if not _API_KEY and not _BASIC_PASSWORD:
        if not _is_loopback(host):
            raise RuntimeError(
                f"Refusing to serve on {host}:{port} without authentication: this API executes "
                "code and shell commands. Set RAVENCODE_API_KEY or pass --password."
            )
        logger.warning("Serving loopback-only without authentication on {}:{}", host, port)

    uvicorn.run(app, host=host, port=port, log_level="info")

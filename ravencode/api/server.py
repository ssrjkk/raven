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

from ravencode.runtime.agent_core import ReActAgent
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
    conv = Conversation()
    conv.messages = [{"role": m.role, "content": m.content or ""} for m in messages]
    return conv


async def _run_agent_nonstream(messages: list[ChatMessage], model: str, max_tokens: int) -> ChatCompletionResponse:
    conv = _openai_messages_to_conversation(messages)
    agent = ReActAgent(conversation=conv, max_steps=20)
    try:
        result = await agent.run(messages[-1].content or "")
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
    conv = _openai_messages_to_conversation(messages)
    agent = ReActAgent(conversation=conv, max_steps=20)

    yield f"data: {json.dumps({'id': f'chatcmpl-{uuid4().hex[:12]}', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"

    try:
        result = await agent.run(messages[-1].content or "")
    except Exception as exc:
        logger.error("Agent stream run failed: {}", exc)
        result = "Agent execution error"

    for chunk in [result[i : i + 100] for i in range(0, len(result), 100)]:
        yield f"data: {json.dumps({'id': f'chatcmpl-{uuid4().hex[:12]}', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {'content': chunk}, 'finish_reason': None}]})}\n\n"
        await asyncio.sleep(0)

    yield f"data: {json.dumps({'id': f'chatcmpl-{uuid4().hex[:12]}', 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
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

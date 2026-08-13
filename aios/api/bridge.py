from __future__ import annotations

import asyncio
import hmac
import json
from typing import Any, cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel, Field

from aios.runtime.adapter import RuntimeAdapter
from raven.core.agents.truthful_orchestrator import TruthfulResult
from raven.core.config import settings
from raven.core.llm.protocol import LLMClientProtocol
from ravencode.agents.multi import MultiAgentOrchestrator, SubTask
from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.api.client import AIOSClient
from ravencode.runtime.agent_core import AgentConfig, AgentEvent, EventEmitter, ReActAgent
from ravencode.runtime.session import SessionStore

router = APIRouter(prefix="/aios", tags=["ai-os-mvp"])
_orch = Orchestrator()
_client = AIOSClient()
_multi = MultiAgentOrchestrator()
_session_store = SessionStore()


class AIRequest(BaseModel):
    prompt: str
    task: str = "code"
    model: str | None = None


class AIResponse(BaseModel):
    text: str
    model: str
    provider: str


class ExecRequest(BaseModel):
    command: str


class ExecResponse(BaseModel):
    output: str
    error: str | None = None


class AgentDispatchRequest(BaseModel):
    task: str
    agent_type: str = "autonomous"
    memory_path: str | None = None
    max_steps: int | None = None


class AgentDispatchResponse(BaseModel):
    agent: str
    success: bool
    data: Any = None
    error: str | None = None
    steps: int = 0


class MultiAgentRequest(BaseModel):
    tasks: list[dict[str, Any]]
    mode: str = "sequential"
    max_concurrent: int = Field(default=3, ge=1, le=20)


class TruthfulRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000, description="User query")
    context: str = Field(default="", max_length=20_000, description="Optional project context")
    model: str | None = Field(default=None, max_length=200, description="Model override")


class TruthfulResponse(BaseModel):
    status: str
    content: str
    thinking_process: str


@router.post("/ai", response_model=AIResponse)
async def aios_gateway(req: AIRequest):
    logger.debug("aios_gateway called: task={}, model={}", req.task, req.model)
    result = await _client.ask(prompt=req.prompt, task=req.task, model=req.model)
    return AIResponse(text=result.text, model=result.model, provider=result.provider)


@router.post("/exec", response_model=ExecResponse)
async def aios_exec(req: ExecRequest):
    try:
        output = await RuntimeAdapter.run_command(req.command)
        return ExecResponse(output=output)
    except Exception as exc:
        logger.error("Exec failed: {}", exc)
        return ExecResponse(output="", error=str(exc))


@router.post("/agent", response_model=AgentDispatchResponse)
async def aios_agent_dispatch(req: AgentDispatchRequest):
    try:
        agent_type = AgentType(req.agent_type)
    except ValueError:
        valid = [e.value for e in AgentType]
        return AgentDispatchResponse(agent=req.agent_type, success=False, error=f"Invalid agent type. Valid: {valid}")
    result = await _orch.dispatch(task=req.task, agent_type=agent_type, memory_path=req.memory_path)
    return AgentDispatchResponse(
        agent=result.agent,
        success=result.success,
        data=result.data,
        error=result.error,
        steps=result.steps,
    )


def _critical_providers_config() -> dict[str, Any]:
    if not settings.critical_provider or not settings.critical_api_key:
        return {}
    return {settings.critical_provider: {"api_key": settings.critical_api_key.get_secret_value()}}


_critical_router: LLMClientProtocol | None = None


def _get_critical_router() -> LLMClientProtocol:
    global _critical_router
    if _critical_router is None:
        from raven.core.llm import LLMRouter

        _critical_router = cast(LLMClientProtocol, LLMRouter(providers_config=_critical_providers_config()))
    return _critical_router


def _reset_critical_router() -> None:
    global _critical_router
    _critical_router = None


async def run_truthful(prompt: str, context: str, model: str | None = None) -> TruthfulResult:
    from raven.core.agents.truthful_orchestrator import TruthfulOrchestrator

    resolved_model = model or settings.critical_model or settings.default_model
    return await TruthfulOrchestrator(_get_critical_router(), model=resolved_model).process(prompt, context)


@router.post("/agent/truthful", response_model=TruthfulResponse)
async def aios_agent_truthful(req: TruthfulRequest):
    try:
        result = await run_truthful(req.prompt, req.context, req.model)
    except Exception as e:
        logger.error("aios_agent_truthful failed: {}", e)
        return TruthfulResponse(
            status="error",
            content=f"[error: {e}]",
            thinking_process="",
        )
    return TruthfulResponse(status=result.status, content=result.content, thinking_process=result.thinking_process)


@router.post("/agent/multi", response_model=list[dict[str, Any]])
async def aios_multi_agent(req: MultiAgentRequest):
    subtasks = [
        SubTask(
            description=t.get("description", ""),
            agent_type=AgentType(t.get("agent_type", "autonomous")),
            depends_on=t.get("depends_on"),
        )
        for t in req.tasks
    ]
    if req.mode == "parallel":
        results = await _multi.run_parallel(subtasks, max_concurrent=req.max_concurrent)
    elif req.mode == "dag":
        results = await _multi.run_dag(subtasks)
    else:
        results = await _multi.run_sequential(subtasks)
    return [
        {
            "index": r.index,
            "description": r.description,
            "success": r.result.success,
            "data": r.result.data,
            "error": r.result.error,
            "duration": r.duration,
        }
        for r in results
    ]


@router.get("/sessions")
async def aios_list_sessions():
    sessions = await asyncio.to_thread(_session_store.list)
    return {"sessions": sessions}


@router.delete("/sessions/{session_id}")
async def aios_delete_session(session_id: str):
    deleted = await _session_store.delete(session_id)
    return {"deleted": deleted}


async def _ws_auth_payload(ws: WebSocket) -> dict[str, Any] | None:
    token = ws.query_params.get("token", "")
    if not token:
        return None
    from raven.core.auth.auth_handler import auth_handler

    secret = settings.web_secret_key.get_secret_value()
    if secret and hmac.compare_digest(token, secret):
        return {"sub": "admin", "role": "admin"}
    return await auth_handler.decode_token(token)


async def _require_ws_auth(ws: WebSocket) -> dict[str, Any] | None:
    payload = await _ws_auth_payload(ws)
    if payload is None:
        logger.warning("[aios] rejecting unauthenticated WebSocket")
        await ws.close(code=1008, reason="Authentication required")
    return payload


@router.websocket("/ws")
async def aios_websocket(ws: WebSocket):
    if await _require_ws_auth(ws) is None:
        return
    await ws.accept()
    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"error": "invalid JSON"}))
                continue

            action = msg.get("action", "")
            if action == "ask":
                prompt = msg.get("prompt", "")
                task = msg.get("task", "code")
                model = msg.get("model")

                result = await _client.ask(prompt=prompt, task=task, model=model)
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "result",
                            "text": result.text,
                            "model": result.model,
                            "provider": result.provider,
                        }
                    )
                )
            elif action == "ask_stream":
                messages = msg.get("messages", [])
                tools = msg.get("tools")
                model = msg.get("model")

                await ws.send_text(json.dumps({"type": "stream_start"}))
                async for token in _client.ask_stream(messages=messages, tools=tools, model=model):
                    await ws.send_text(json.dumps({"type": "token", "content": token}))
                await ws.send_text(json.dumps({"type": "stream_end"}))
            elif action == "agent":
                task_text = msg.get("task", "")
                agent_type = msg.get("agent_type", "autonomous")
                agent_result = await _orch.dispatch(task=task_text, agent_type=AgentType(agent_type))
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "agent_result",
                            "success": agent_result.success,
                            "data": agent_result.data,
                            "error": agent_result.error,
                            "steps": agent_result.steps,
                        }
                    )
                )
            elif action == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            else:
                await ws.send_text(json.dumps({"error": f"unknown action: {action}"}))
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected")


@router.websocket("/ws/agent")
async def aios_agent_ws(ws: WebSocket):
    if await _require_ws_auth(ws) is None:
        return
    await ws.accept()
    ee = EventEmitter()

    async def send_event(event: AgentEvent) -> None:
        try:
            await ws.send_json(
                {
                    "type": event.type,
                    "data": event.data,
                    "timestamp": event.timestamp,
                }
            )
        except Exception as exc:
            logger.debug("Failed to send WS event {}: {}", event.type, exc)

    ee.on("step_start", send_event)
    ee.on("tool_call", send_event)
    ee.on("tool_result", send_event)
    ee.on("artifact_created", send_event)
    ee.on("message", send_event)
    ee.on("truthful", send_event)
    ee.on("done", send_event)

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": {"message": "invalid JSON"}})
                continue

            prompt = msg.get("prompt", "")
            if not prompt:
                await ws.send_json({"type": "error", "data": {"message": "prompt required"}})
                continue

            config = AgentConfig(
                max_steps=msg.get("max_steps", 30),
                event_emitter=ee,
                diff_preview=msg.get("diff_preview", True),
                proactive_scan=msg.get("proactive_scan", True),
                max_tool_retries=msg.get("max_tool_retries", 3),
            )
            agent = ReActAgent(config=config)
            if msg.get("truthful"):
                model = msg.get("model")
                try:
                    truthful_result = await run_truthful(prompt, "", model)
                except ValueError as exc:
                    await ws.send_json({"type": "error", "data": {"message": str(exc)}})
                    continue
                await ws.send_json(
                    {
                        "type": "final",
                        "data": {
                            "status": truthful_result.status,
                            "content": truthful_result.content,
                            "thinking_process": truthful_result.thinking_process,
                        },
                    }
                )
                continue
            result = await agent.run(prompt)
            if not result.startswith("[aborted"):
                await ws.send_json({"type": "final", "data": {"content": result}})
    except WebSocketDisconnect:
        logger.debug("[aios] agent WS disconnected")


@router.get("/health")
async def aios_health():
    return {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}


@router.get("/metrics")
async def aios_metrics():
    from raven.core.metrics import metrics

    return metrics.snapshot()


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def aios_metrics_prometheus():
    from raven.core.metrics import metrics

    return metrics.prometheus()

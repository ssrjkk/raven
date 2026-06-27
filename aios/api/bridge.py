from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from aios.runtime.adapter import RuntimeAdapter
from ravencode.agents.multi import MultiAgentOrchestrator, SubTask
from ravencode.agents.orchestrator import AgentType, Orchestrator
from ravencode.api.client import AIOSClient
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
    max_concurrent: int = 3


@router.post("/ai", response_model=AIResponse)
async def aios_gateway(req: AIRequest):
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
    return {"sessions": _session_store.list()}


@router.delete("/sessions/{session_id}")
async def aios_delete_session(session_id: str):
    deleted = await _session_store.delete(session_id)
    return {"deleted": deleted}


@router.websocket("/ws")
async def aios_websocket(ws: WebSocket):
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
                await ws.send_text(json.dumps({
                    "type": "result",
                    "text": result.text,
                    "model": result.model,
                    "provider": result.provider,
                }))
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
                result = await _orch.dispatch(task=task_text, agent_type=AgentType(agent_type))
                await ws.send_text(json.dumps({
                    "type": "agent_result",
                    "success": result.success,
                    "data": result.data,
                    "error": result.error,
                    "steps": result.steps,
                }))
            elif action == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            else:
                await ws.send_text(json.dumps({"error": f"unknown action: {action}"}))
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected")


@router.get("/health")
async def aios_health():
    return {"status": "ok", "module": "ai-os-mvp", "version": "0.1.0"}

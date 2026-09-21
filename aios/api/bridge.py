from __future__ import annotations

import asyncio
import contextlib
import difflib
import hmac
import json
from pathlib import Path
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
from ravencode.runtime.workspace import confine

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


def _compute_confirm_diff(tool_name: str, args: dict[str, Any]) -> str | None:
    file_path = args.get("path") or args.get("file_path") or args.get("file")
    if not file_path:
        return None
    try:
        p = Path(file_path)
        if not p.is_absolute():
            p = Path.cwd() / p
        old_content = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except Exception:
        return None

    new_content: str | None = None
    if tool_name in ("write_file", "write"):
        new_content = args.get("content", "")
    elif tool_name in ("edit_file", "edit"):
        old_str = args.get("old_string", "")
        new_str = args.get("new_string", "")
        if old_str and old_str in old_content:
            new_content = old_content.replace(old_str, new_str, 1)
        elif old_str:
            lines_old = [ln.rstrip() for ln in old_str.splitlines()]
            lines_content = old_content.splitlines(keepends=True)
            stripped = [ln.rstrip() for ln in [lc.rstrip("\r\n") for lc in lines_content]]
            n = len(lines_old)
            for i in range(len(stripped) - n + 1):
                if stripped[i : i + n] == lines_old:
                    start = sum(len(ln) for ln in lines_content[:i])
                    end = sum(len(ln) for ln in lines_content[: i + n])
                    new_content = old_content[:start] + new_str + old_content[end:]
                    break
    elif tool_name == "smart_edit":
        new_content = args.get("new_content") or args.get("content")
    elif tool_name == "patch_file":
        return None

    if new_content is None:
        return None
    diff = "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
    )
    return diff if diff else None


@router.websocket("/ws/agent")
async def aios_agent_ws(ws: WebSocket):
    if await _require_ws_auth(ws) is None:
        return
    await ws.accept()
    try:
        from ravencode.runtime.mcp_tools import ensure_mcp_tools

        await ensure_mcp_tools()  # idempotent; best-effort per connection
    except Exception as exc:
        logger.debug("MCP tools unavailable on WS connect: {}", exc)
    ee = EventEmitter()

    async def _confirm(name: str, args: dict[str, Any]) -> bool:
        try:
            diff = _compute_confirm_diff(name, args)
            payload: dict[str, Any] = {"tool": name, "arguments": args}
            if diff:
                payload["diff"] = diff
            await ws.send_json({"type": "confirm_request", "data": payload})
            deadline = asyncio.get_event_loop().time() + 60
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return False
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=remaining)
                    reply = json.loads(raw)
                except (TimeoutError, json.JSONDecodeError):
                    return False
                if reply.get("type") == "confirm":
                    return bool(reply.get("data", {}).get("approved", False))
                if reply.get("type") == "deny":
                    return False
        except Exception:
            return False

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

    ee.on("token", send_event)
    ee.on("step_start", send_event)
    ee.on("tool_call", send_event)
    ee.on("tool_result", send_event)
    ee.on("artifact_created", send_event)
    ee.on("message", send_event)
    ee.on("truthful", send_event)
    ee.on("done", send_event)

    agent_task: asyncio.Task[str] | None = None
    try:
        while True:
            if agent_task is None or agent_task.done():
                if agent_task is not None and agent_task.done():
                    try:
                        result = agent_task.result()
                    except asyncio.CancelledError:
                        result = "[aborted]"
                    if not result.startswith("[aborted"):
                        await ws.send_json({"type": "final", "data": {"content": result}})
                    agent_task = None
                data = await ws.receive_text()
            else:
                recv_task = asyncio.create_task(ws.receive_text())
                done, _pending = await asyncio.wait(
                    {agent_task, recv_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if recv_task in _pending:
                    recv_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await recv_task
                if agent_task in done:
                    continue
                if recv_task in done:
                    data = recv_task.result()
                else:
                    continue

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "data": {"message": "invalid JSON"}})
                continue

            if msg.get("type") == "cancel":
                if agent_task and not agent_task.done():
                    agent_task.cancel()
                    await ws.send_json({"type": "done", "data": {"reason": "cancelled", "steps": 0}})
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
                confirm_dangerous=True,
                confirm_callback=_confirm,
                stream_tokens=bool(msg.get("stream", True)),
                repo_map=bool(msg.get("repo_map", True)),
                priority="high" if msg.get("interactive", True) else "normal",
                plan_mode=msg.get("mode", "") == "plan",
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
            agent_task = asyncio.create_task(agent.run(prompt))
    except WebSocketDisconnect:
        if agent_task and not agent_task.done():
            agent_task.cancel()
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


@router.post("/completion")
async def aios_completion(payload: dict[str, Any]) -> dict[str, Any]:
    prefix = payload.get("prefix", "")
    suffix = payload.get("suffix", "")
    language = payload.get("language", "")
    if not prefix and not suffix:
        return {"completion": ""}
    try:
        from ravencode.api.client import AIOSClient

        client = AIOSClient()
        prompt_parts = []
        if language:
            prompt_parts.append(f"Language: {language}")
        prompt_parts.append("Complete the code. Reply with ONLY the completion text, no explanation, no markdown fences.")
        if prefix:
            prompt_parts.append(f"\nCode before cursor:\n{prefix[-2000:]}")
        if suffix:
            prompt_parts.append(f"\nCode after cursor:\n{suffix[:500]}")
        prompt_parts.append("\nCompletion:")
        prompt = "\n".join(prompt_parts)
        resp = await client.ask(prompt, task="code")
        completion = resp.text.strip()
        if completion.startswith("```"):
            lines = completion.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            completion = "\n".join(lines)
        return {"completion": completion}
    except Exception:
        logger.debug("Completion failed")
        return {"completion": "", "error": "Completion failed"}


@router.post("/inline-edit")
async def aios_inline_edit(payload: dict[str, Any]) -> dict[str, Any]:
    code = str(payload.get("code", ""))
    instruction = str(payload.get("instruction", ""))
    language = str(payload.get("language", ""))
    if not code or not instruction:
        return {"edited_code": code, "diff": ""}
    try:
        import difflib

        from ravencode.api.client import AIOSClient

        client = AIOSClient()
        lang_hint = f" ({language})" if language else ""
        prompt = (
            f"You are a code editor. Apply the following instruction to the code{lang_hint}.\n"
            f"Return ONLY the modified code — no explanation, no markdown fences.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Code:\n{code}\n\n"
            f"Edited code:"
        )
        resp = await client.ask(prompt, task="code")
        edited = resp.text.strip()
        if edited.startswith("```"):
            lines = edited.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            edited = "\n".join(lines)
        diff_lines = list(difflib.unified_diff(
            code.splitlines(keepends=True),
            edited.splitlines(keepends=True),
            fromfile="original", tofile="edited",
        ))
        return {"edited_code": edited, "diff": "".join(diff_lines)}
    except Exception:
        logger.debug("Inline edit failed")
        return {"edited_code": code, "diff": "", "error": "Inline edit failed"}


@router.get("/workspace/tree")
async def workspace_tree(path: str = ".") -> dict[str, Any]:
    from pathlib import Path as PathLib

    try:
        root = confine(path)
    except PermissionError:
        return {"error": "Access denied: path outside workspace", "tree": []}
    if not root.is_dir():
        return {"error": "Path is not a directory", "tree": []}

    def _build_tree(dir_path: PathLib, depth: int = 0) -> dict[str, Any] | None:
        if depth > 5:
            return None
        try:
            items = []
            for item in sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if item.name.startswith(".") or item.name in ("node_modules", "__pycache__", "venv", ".venv"):
                    continue
                if item.is_dir():
                    children = _build_tree(item, depth + 1)
                    if children:
                        items.append(children)
                else:
                    items.append({
                        "type": "file",
                        "name": item.name,
                        "path": str(item.relative_to(root)),
                    })
            return {
                "type": "directory",
                "name": dir_path.name if dir_path != root else root.name,
                "path": str(dir_path.relative_to(root)) if dir_path != root else ".",
                "children": items,
            }
        except PermissionError:
            return None

    tree = _build_tree(root)
    return {"root": str(root), "tree": tree}


@router.get("/workspace/read")
async def workspace_read(path: str) -> dict[str, Any]:
    try:
        file_path = confine(path)
    except PermissionError:
        return {"error": "Access denied: path outside workspace"}
    if not file_path.is_file():
        return {"error": "File not found"}
    try:
        content = file_path.read_text(encoding="utf-8")
        return {"path": str(file_path), "content": content, "size": len(content)}
    except Exception:
        return {"error": "Failed to read file"}


@router.post("/workspace/write")
async def workspace_write(payload: dict[str, Any]) -> dict[str, Any]:
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not path:
        return {"error": "Path required"}
    try:
        file_path = confine(path)
    except PermissionError:
        return {"error": "Access denied: path outside workspace"}
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(file_path), "size": len(content)}
    except Exception:
        return {"error": "Failed to write file"}


@router.post("/search")
async def aios_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query", "")
    path = payload.get("path", ".")
    limit = min(int(payload.get("limit", 100)), 500)
    if not query:
        return {"results": [], "error": "Query required"}
    try:
        root = confine(path)
    except PermissionError:
        return {"results": [], "error": "Access denied: path outside workspace"}
    if not root.is_dir():
        return {"results": [], "error": "Path is not a directory"}
    results = await asyncio.to_thread(_rg_search, query, root, limit)
    return {"results": results, "count": len(results)}


def _rg_search(query: str, root: Path, limit: int) -> list[dict[str, Any]]:
    import shutil
    import subprocess

    rg = shutil.which("rg")
    if rg:
        try:
            proc = subprocess.run(
                [rg, "--json", "--max-count", "5", "-n", query, str(root)],
                capture_output=True, text=True, timeout=10, cwd=str(root),
            )
            results: list[dict[str, Any]] = []
            for line in proc.stdout.splitlines():
                if len(results) >= limit:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "match":
                    continue
                data = obj.get("data", {})
                path = data.get("path", {}).get("text", "")
                line_num = data.get("line_number", 0)
                text = data.get("lines", {}).get("text", "").rstrip("\n")
                rel = str(Path(path).relative_to(root)) if Path(path).is_absolute() else path
                results.append({"file": rel, "line": line_num, "text": text})
            return results
        except Exception as exc:
            logger.debug("ripgrep search failed, falling back to Python: {}", exc)

    results = []
    try:
        import re as _re
        pattern = _re.compile(_re.escape(query))
    except Exception:
        return results
    for fpath in root.rglob("*"):
        if len(results) >= limit:
            break
        if not fpath.is_file():
            continue
        if any(p in str(fpath) for p in (".git", "node_modules", "__pycache__", ".venv")):
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if len(results) >= limit:
                break
            if pattern.search(line):
                rel = str(fpath.relative_to(root))
                results.append({"file": rel, "line": i, "text": line.rstrip()})
    return results


@router.post("/search/semantic")
async def aios_search_semantic(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query", "")
    path = payload.get("path", ".")
    top_k = min(int(payload.get("top_k", 10)), 50)
    if not query:
        return {"results": [], "error": "Query required"}
    try:
        root = confine(path)
    except PermissionError:
        return {"results": [], "error": "Access denied: path outside workspace"}
    if not root.is_dir():
        return {"results": [], "error": "Path is not a directory"}

    def _search() -> list[dict[str, Any]]:
        from ravencode.runtime.code_search import RepoIndex
        idx = RepoIndex()
        raw = idx.search(root, query, k=top_k)
        results: list[dict[str, Any]] = []
        for item in raw:
            lines = item.split("\n", 1)
            header = lines[0]
            text = lines[1] if len(lines) > 1 else ""
            file_part, _, line_range = header.rpartition(":")
            results.append({"file": file_part, "range": line_range, "text": text})
        return results
    results = await asyncio.to_thread(_search)
    return {"results": results, "count": len(results)}


@router.get("/sessions/{session_id}")
async def aios_get_session(session_id: str):
    data = await asyncio.to_thread(_session_read, session_id)
    if data is None:
        return {"error": "Session not found"}
    return data


def _session_read(session_id: str) -> dict[str, Any] | None:
    import re as _re
    if not _re.match(r"^[A-Za-z0-9_-]{1,128}$", session_id):
        return None
    from pathlib import Path as PathLib
    p = PathLib("data/sessions") / f"{session_id}.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        data["id"] = session_id
        return data
    except (json.JSONDecodeError, OSError):
        return None

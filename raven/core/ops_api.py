from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from raven.core.config import settings
from raven.core.monitor.engine import MonitorEngine
from raven.core.routine.engine import RoutineEngine

if TYPE_CHECKING:
    from raven.core.features import FeatureFlags
    from raven.core.gateway.gateway import Gateway


def create_ops_router(gateway: Gateway, features: FeatureFlags) -> APIRouter:
    router = APIRouter()

    @router.get("/api/monitor/list")
    async def api_monitor_list(request: Request, limit: int = 50, offset: int = 0):
        eng: MonitorEngine = request.app.state.monitor_engine
        limit = min(limit, 1000)
        items = [
            {
                "id": m.id,
                "name": m.name,
                "type": m.type.value,
                "target": m.target,
                "interval_seconds": m.interval_seconds,
                "effective_interval": eng.effective_interval(m.id, m.interval_seconds),
                "status": m.status.value,
                "group": m.group,
                "last_check": {"status": m.last_check.status, "checked_at": m.last_check.checked_at}
                if m.last_check
                else None,
            }
            for m in await eng.list_monitors(limit=limit, offset=offset)
        ]
        return {"items": items, "total": await eng.count_monitors(), "limit": limit, "offset": offset, "version": 1}

    @router.get("/api/monitor/slo")
    async def api_monitor_slo(request: Request, limit: int = 100, offset: int = 0):
        eng: MonitorEngine = request.app.state.monitor_engine
        limit = min(limit, 1000)
        items = await eng.slo_report(limit=limit, offset=offset)
        return {"items": items, "total": len(items), "limit": limit, "offset": offset, "version": 1}

    @router.post("/api/monitor/{action}/{monitor_id}")
    async def api_monitor_toggle(request: Request, action: str, monitor_id: str):
        eng: MonitorEngine = request.app.state.monitor_engine
        if action == "pause":
            await eng.pause_monitor(monitor_id)
        elif action == "resume":
            await eng.resume_monitor(monitor_id)
        return {"ok": True}

    @router.get("/api/tools/policy")
    async def api_tools_policy():
        from raven.core.tools_rbac import ToolPolicyStore
        from raven.tools.register_all import create_tool_registry

        policy = ToolPolicyStore()
        reg = create_tool_registry()
        tools = [
            {
                "name": t.name,
                "category": t.category,
                "dangerous": t.dangerous,
                "allowed_roles": reg.effective_allowed_roles(t.name),
            }
            for t in reg.list()
        ]
        return {"policy": policy.all(), "tools": tools, "version": 1}

    @router.post("/api/tools/policy")
    async def api_tools_policy_set(body: dict[str, Any]):
        from raven.core.tools_rbac import ToolPolicyStore

        tool = str(body.get("tool", ""))
        if not tool:
            raise HTTPException(400, "tool required")
        policy = ToolPolicyStore()
        roles = body.get("roles")
        if roles is None:
            policy.remove(tool)
        else:
            policy.set(tool, [str(r) for r in roles])
        policy.save()
        return {"ok": True, "tool": tool, "roles": policy.get(tool), "version": 1}

    @router.get("/api/routine/list")
    async def api_routine_list(request: Request, limit: int = 50, offset: int = 0):
        eng: RoutineEngine = request.app.state.routine_engine
        limit = min(limit, 1000)
        items = [
            {
                "id": r.id,
                "name": r.name,
                "action": r.action.value,
                "schedule": r.schedule,
                "trigger": r.trigger.value,
                "status": r.status.value,
                "last_run_status": r.last_run_status,
            }
            for r in await eng.list_routines(limit=limit, offset=offset)
        ]
        return {
            "items": items,
            "total": await eng._store.count_routines(),
            "limit": limit,
            "offset": offset,
            "version": 1,
        }

    @router.post("/api/routine/create")
    async def api_routine_create(request: Request, body: dict[str, Any]):
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

        eng: RoutineEngine = request.app.state.routine_engine
        routine = Routine(
            name=body.get("name", "New Routine"),
            action=RoutineAction(body.get("action", "send_message")),
            trigger=RoutineTrigger(body.get("trigger", "manual")),
            schedule=body.get("schedule", "08:00"),
            status=RoutineStatus.ACTIVE,
            user_id=body.get("user_id", "system"),
            channel=body.get("channel", "internal"),
            config=body.get("config", {}),
        )
        await eng._store.save_routine(routine)
        return {"ok": True, "id": routine.id}

    @router.delete("/api/routine/{routine_id}")
    async def api_routine_delete(request: Request, routine_id: str):
        eng: RoutineEngine = request.app.state.routine_engine
        await eng._store.delete_routine(routine_id)
        return {"ok": True}

    @router.post("/api/routine/{action}/{routine_id}")
    async def api_routine_toggle(request: Request, action: str, routine_id: str):
        eng: RoutineEngine = request.app.state.routine_engine
        if action == "pause":
            await eng.pause_routine(routine_id)
        elif action == "resume":
            await eng.resume_routine(routine_id)
        return {"ok": True}

    if features.is_enabled("planner"):

        @router.get("/api/task/list")
        async def api_task_list(limit: int = 50, offset: int = 0):
            from raven.core.task_engine.store import TaskStore

            store = TaskStore(settings.resolved_db_path)
            limit = min(limit, 1000)
            items = [
                {
                    "id": t.id,
                    "goal": t.goal,
                    "status": t.status.value,
                    "steps": [
                        {"order": s.order, "description": s.description, "tool": s.tool, "status": s.status.value}
                        for s in t.steps
                    ],
                    "created_at": t.created_at,
                }
                for t in await store.list_tasks(limit=limit, offset=offset)
            ]
            return {
                "items": items,
                "total": await store.count_tasks(),
                "limit": limit,
                "offset": offset,
                "version": 1,
            }

        @router.post("/api/task/run")
        async def api_task_run(request: Request, body: dict[str, Any]):
            from raven.core.task_engine.planner import TaskPlanner
            from raven.core.task_engine.runner import TaskRunner
            from raven.core.task_engine.store import TaskStore
            from raven.tools.register_all import create_task_tool_registry

            goal = body.get("goal", "")
            if not goal:
                raise HTTPException(400, "goal required")
            tools = create_task_tool_registry()
            store = TaskStore(settings.resolved_db_path)
            planner = TaskPlanner(tools)
            runner = TaskRunner(store, tools)
            task = await planner.plan(goal, gateway.llm)
            await runner.submit(task)
            bg_task = asyncio.create_task(runner.wait(task.id, timeout=600))
            if not hasattr(request.app.state, "_bg_tasks"):
                request.app.state._bg_tasks = set()
            request.app.state._bg_tasks.add(bg_task)
            bg_task.add_done_callback(request.app.state._bg_tasks.discard)
            return {"id": task.id}

        @router.post("/api/task/{task_id}/cancel")
        async def api_task_cancel(task_id: str):
            from raven.core.task_engine.runner import TaskRunner
            from raven.core.task_engine.store import TaskStore
            from raven.tools.register_all import create_tool_registry

            tools = create_tool_registry()
            store = TaskStore(settings.resolved_db_path)
            runner = TaskRunner(store, tools)
            ok = await runner.cancel(task_id)
            return {"ok": ok}

    else:
        logger.debug("Task endpoints skipped (planner disabled)")

    @router.get("/api/code/list")
    async def api_code_sessions(limit: int = 20, offset: int = 0):
        from raven.core.coder.session import CodingSessionManager

        mgr = CodingSessionManager(settings.resolved_db_path)
        limit = min(limit, 1000)
        items = [
            {
                "id": s.id,
                "goal": s.goal,
                "status": s.status.value,
                "project_path": s.project_path,
                "files": len(s.files),
            }
            for s in await mgr.list_sessions(limit=limit, offset=offset)
        ]
        return {"items": items, "total": await mgr.count_sessions(), "limit": limit, "offset": offset, "version": 1}

    return router

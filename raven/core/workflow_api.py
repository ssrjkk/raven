from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.core.workflow.runner import TemplateRunner
from raven.core.workflow.store import WorkflowStore

_store: WorkflowStore | None = None
_cleanup_tasks: set[asyncio.Task[None]] = set()


def set_workflow_store(store: WorkflowStore) -> None:
    global _store
    _store = store


def _get_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store


class InstantiateRequest(BaseModel):
    user_id: str = "system"
    channel: str = "internal"
    config: dict[str, Any] = {}


class ScheduleRequest(BaseModel):
    user_id: str = "system"
    channel: str = "internal"
    config: dict[str, Any] = {}


def create_workflow_router() -> APIRouter:
    router = APIRouter(prefix="/api/workflows", tags=["workflows"])

    @router.get("/templates")
    def api_workflow_templates(category: str | None = None):
        store = _get_store()
        templates = store.list_templates(category=category) if category else store.list_templates()
        return {
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "category": t.category.value,
                    "trigger": t.trigger.value,
                    "icon": t.icon,
                    "config_schema": t.config_schema,
                    "has_steps_goal": bool(t.steps_goal),
                    "has_predefined_steps": bool(t.predefined_steps),
                }
                for t in templates
            ],
            "count": len(templates),
        }

    @router.get("/categories")
    def api_workflow_categories():
        store = _get_store()
        return {"categories": store.list_categories()}

    @router.get("/templates/{template_id}")
    def api_workflow_get_template(template_id: str):
        store = _get_store()
        t = store.get(template_id)
        if not t:
            raise HTTPException(404, f"Template '{template_id}' not found")
        return {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "category": t.category.value,
            "trigger": t.trigger.value,
            "icon": t.icon,
            "config_schema": t.config_schema,
            "default_schedule": t.default_schedule,
            "default_interval": t.default_interval,
            "steps_goal": t.steps_goal,
            "predefined_steps": [
                {"description": s.description, "tool": s.tool, "params": s.params} for s in (t.predefined_steps or [])
            ],
        }

    @router.post("/templates/{template_id}/instantiate")
    async def api_workflow_instantiate(template_id: str, req: InstantiateRequest):
        from raven.core.config import settings
        from raven.core.task_engine.runner import TaskRunner
        from raven.core.task_engine.store import TaskStore
        from raven.tools.register_all import create_tool_registry

        store = _get_store()
        template = store.get(template_id)
        if not template:
            raise HTTPException(404, f"Template '{template_id}' not found")
        tools = create_tool_registry()
        task_store = TaskStore(settings.resolved_db_path)
        runner = TaskRunner(task_store, tools)
        tpl_runner = TemplateRunner(runner, task_store, tools, None)
        try:
            task_id = await tpl_runner.instantiate(
                template=template, user_id=req.user_id, channel=req.channel, config=req.config
            )

            def _close_store() -> None:
                _cleanup_tasks.add(asyncio.create_task(task_store.close()))

            runner.on_complete(task_id, _close_store)
            return {"ok": True, "task_id": task_id}
        except Exception as e:
            await task_store.close()
            logger.warning("[workflow] instantiate failed: {}", e)
            raise internal_error(e) from e

    @router.post("/templates/{template_id}/schedule")
    async def api_workflow_schedule(template_id: str, req: ScheduleRequest):
        from raven.core.config import settings

        store = _get_store()
        template = store.get(template_id)
        if not template:
            raise HTTPException(404, f"Template '{template_id}' not found")
        try:
            routine_id = await TemplateRunner.schedule_as_routine(
                template=template,
                db_path=str(settings.resolved_db_path),
                user_id=req.user_id,
                channel=req.channel,
                config=req.config,
            )
            return {"ok": True, "routine_id": routine_id}
        except Exception as e:
            logger.warning("[workflow] schedule failed: {}", e)
            raise internal_error(e) from e

    return router

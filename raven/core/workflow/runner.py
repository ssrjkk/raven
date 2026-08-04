from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger

from raven.core.workflow.models import TemplateTrigger, WorkflowTemplate

if TYPE_CHECKING:
    from raven.core.llm import LLMRouter
    from raven.core.task_engine.runner import TaskRunner
    from raven.core.task_engine.store import TaskStore
    from raven.core.task_engine.tool_registry import ToolRegistry


def _apply_schema_defaults(config: dict[str, Any] | None, schema: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(config or {})
    for key, prop in schema.get("properties", {}).items():
        if key not in cfg and "default" in prop:
            cfg[key] = prop["default"]
    return cfg


class TemplateRunner:
    def __init__(
        self,
        task_runner: TaskRunner,
        task_store: TaskStore,
        tool_registry: ToolRegistry,
        llm: LLMRouter | None = None,
    ):
        self._task_runner = task_runner
        self._task_store = task_store
        self._tools = tool_registry
        self._llm = llm

    async def instantiate(
        self,
        template: WorkflowTemplate,
        user_id: str = "system",
        channel: str = "internal",
        config: dict[str, Any] | None = None,
    ) -> str:
        cfg = _apply_schema_defaults(config, template.config_schema)
        try:
            goal = (template.steps_goal or template.description).format(**cfg)
        except (KeyError, ValueError) as e:
            msg = f"Invalid config for template '{template.id}': {e}"
            raise ValueError(msg) from e

        task_id = uuid.uuid4().hex[:16]

        from raven.core.task_engine.models import Task, TaskPriority, TaskStatus, TaskStep

        task = Task(
            id=task_id,
            user_id=user_id,
            channel=channel,
            goal=goal,
            priority=TaskPriority.MEDIUM,
            status=TaskStatus.PENDING,
            steps=[],
            created_at=time.time(),
            updated_at=time.time(),
        )
        task.metadata = {"template_id": template.id, "template_name": template.name, "config": cfg}

        if template.predefined_steps:
            for i, s in enumerate(template.predefined_steps):
                step = TaskStep(
                    id=f"{task_id}-s{i}",
                    task_id=task_id,
                    order=i,
                    description=s.description,
                    tool=s.tool or "",
                    params=s.params,
                )
                task.steps.append(step)
        elif self._llm is not None:
            from raven.core.task_engine.planner import TaskPlanner

            planner = TaskPlanner(self._tools)
            try:
                planned = await planner.plan(
                    goal=goal, llm=self._llm, task_id=task_id, user_id=user_id, channel=channel
                )
            except Exception as e:
                msg = f"Task planning failed for template '{template.id}': {e}"
                raise RuntimeError(msg) from e
            task.steps = planned.steps
            task.plan_summary = planned.plan_summary
        else:
            msg = (
                f"Template '{template.id}' has no predefined steps and no LLM is configured. "
                "Provide predefined_steps or configure an LLM."
            )
            raise ValueError(msg)

        await self._task_runner.submit(task)
        logger.info("Instantiated workflow '{}' -> task {}", template.name, task_id)
        return task_id

    @staticmethod
    async def schedule_as_routine(
        template: WorkflowTemplate,
        db_path: str = "data/raven.db",
        user_id: str = "system",
        channel: str = "internal",
        config: dict[str, Any] | None = None,
    ) -> str:
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

        trigger_map = {
            TemplateTrigger.SCHEDULED: RoutineTrigger.SCHEDULED,
            TemplateTrigger.INTERVAL: RoutineTrigger.INTERVAL,
            TemplateTrigger.MANUAL: RoutineTrigger.MANUAL,
            TemplateTrigger.EVENT: RoutineTrigger.EVENT,
        }
        trigger = trigger_map.get(template.trigger, RoutineTrigger.MANUAL)
        suffix = uuid.uuid4().hex[:8]
        routine_id = f"{template.id}-{user_id}-{suffix}"

        if trigger == RoutineTrigger.INTERVAL and template.default_interval is not None:
            schedule = str(template.default_interval)
        elif template.default_schedule is not None:
            schedule = template.default_schedule
        else:
            schedule = "08:00"

        routine = Routine(
            id=routine_id,
            name=template.name,
            action=RoutineAction.SEND_MESSAGE,
            trigger=trigger,
            schedule=schedule,
            status=RoutineStatus.ACTIVE,
            user_id=user_id,
            channel=channel,
            config={"template_id": template.id, "template_config": config or {}},
            created_at=time.time(),
        )
        from raven.core.routine.engine import RoutineEngine, get_routine_engine
        from raven.core.routine.store import RoutineStore

        engine = get_routine_engine()
        if engine is not None:
            await engine.add_routine(routine)
            logger.info("Scheduled workflow '{}' as routine {}", template.name, routine_id)
            return routine_id

        store = RoutineStore(db_path)
        try:
            await store.save_routine(routine)
            logger.info("Scheduled workflow '{}' as routine {}", template.name, routine_id)

            engine = RoutineEngine(store)
            await engine.start()
        except Exception:
            await store.delete_routine(routine_id)
            logger.error("Failed to start routine engine for '{}', rolled back", routine_id)
            raise
        return routine_id

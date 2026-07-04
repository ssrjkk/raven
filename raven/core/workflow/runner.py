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
        cfg = config or {}
        goal = (template.steps_goal or template.description).format(**cfg)
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
            planned = await planner.plan(goal=goal, llm=self._llm, task_id=task_id, user_id=user_id, channel=channel)
            task.steps = planned.steps
            task.plan_summary = planned.plan_summary

        await self._task_runner.submit(task)
        logger.info("Instantiated workflow '{}' -> task {}", template.name, task_id)
        return task_id

    async def schedule_as_routine(
        self,
        template: WorkflowTemplate,
        db_path: str = "data/raven.db",
        user_id: str = "system",
        channel: str = "internal",
        config: dict[str, Any] | None = None,
    ) -> str | None:
        from raven.core.routine.models import Routine, RoutineAction, RoutineStatus, RoutineTrigger

        trigger_map = {
            TemplateTrigger.SCHEDULED: RoutineTrigger.SCHEDULED,
            TemplateTrigger.INTERVAL: RoutineTrigger.INTERVAL,
            TemplateTrigger.MANUAL: RoutineTrigger.MANUAL,
            TemplateTrigger.EVENT: RoutineTrigger.EVENT,
        }
        routine = Routine(
            id=f"{template.id}-{user_id}",
            name=template.name,
            action=RoutineAction.SEND_MESSAGE,
            trigger=trigger_map.get(template.trigger, RoutineTrigger.MANUAL),
            schedule=template.default_schedule or "08:00",
            status=RoutineStatus.ACTIVE,
            user_id=user_id,
            channel=channel,
            config={"template_id": template.id, "template_config": config or {}},
            created_at=time.time(),
        )
        from raven.core.routine.store import RoutineStore

        store = RoutineStore(db_path)
        store.save_routine(routine)
        logger.info("Scheduled workflow '{}' as routine {}", template.name, routine.id)

        from raven.core.routine.engine import RoutineEngine

        engine = RoutineEngine(store)
        await engine.start()
        return routine.id

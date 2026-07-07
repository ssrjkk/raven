from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from loguru import logger


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class StepResult:
    step_id: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    duration: float = 0.0


@dataclass
class WorkflowResult:
    workflow_id: str
    status: WorkflowStatus
    steps: dict[str, StepResult] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    error: str | None = None


@dataclass
class WorkflowStep:
    id: str
    name: str
    handler: Callable[..., Awaitable[Any]] | None = None
    depends_on: list[str] = field(default_factory=list)
    condition: str | None = None
    max_retries: int = 0
    retry_delay: float = 1.0
    timeout: float = 300.0
    params: dict[str, Any] = field(default_factory=dict)


_TEMPLATE_DIR: Path | None = None


def set_template_dir(path: str | Path) -> None:
    global _TEMPLATE_DIR
    _TEMPLATE_DIR = Path(path)


class WorkflowEngine:
    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowResult] = {}
        self._step_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}
        self._workflow_steps: dict[str, list[WorkflowStep]] = {}

    def register_handler(self, name: str, handler: Callable[..., Awaitable[Any]]) -> None:
        self._step_handlers[name] = handler

    async def run_workflow(self, steps: list[WorkflowStep], workflow_id: str | None = None) -> WorkflowResult:
        wid = workflow_id or uuid.uuid4().hex[:12]
        result = WorkflowResult(workflow_id=wid, status=WorkflowStatus.PENDING, start_time=time.time())
        self._workflows[wid] = result
        self._workflow_steps[wid] = steps

        completed: dict[str, Any] = {}
        remaining = {s.id: s for s in steps}
        step_results: dict[str, StepResult] = {}

        try:
            while remaining:
                ready = [
                    s for s in remaining.values()
                    if all(dep in completed for dep in s.depends_on)
                ]
                if not ready:
                    self._handle_missing_deps(remaining, completed, step_results, result)
                    if result.status == WorkflowStatus.FAILED:
                        break
                    ready = [remaining[sid] for sid in remaining]

                tasks = [self._execute_step(s, completed) for s in ready]
                for sr in await asyncio.gather(*tasks):
                    step_results[sr.step_id] = sr
                    if sr.status == StepStatus.SUCCESS:
                        completed[sr.step_id] = sr.output
                    del remaining[sr.step_id]

            self._finalize(result, step_results)
        except Exception as exc:
            result.status = WorkflowStatus.FAILED
            result.error = str(exc)
            logger.exception("Workflow {} failed: {}", wid, exc)

        result.end_time = time.time()
        return result

    def _handle_missing_deps(
        self,
        remaining: dict[str, WorkflowStep],
        completed: dict[str, Any],
        step_results: dict[str, StepResult],
        result: WorkflowResult,
    ) -> None:
        has_failed = False
        for step in remaining.values():
            for dep in step.depends_on:
                if dep not in completed and dep not in remaining:
                    step_results[step.id] = StepResult(
                        step_id=step.id, status=StepStatus.FAILED,
                        error=f"Dependency {dep} not found",
                    )
                    has_failed = True
                    break

        if has_failed:
            result.status = WorkflowStatus.FAILED
            return

        if not any(dep in completed for step in remaining.values() for dep in step.depends_on):
            result.status = WorkflowStatus.FAILED
            result.error = "Circular dependency detected"

    def _finalize(self, result: WorkflowResult, step_results: dict[str, StepResult]) -> None:
        result.steps = step_results
        statuses = {sr.status for sr in step_results.values()}
        if StepStatus.FAILED in statuses:
            result.status = WorkflowStatus.PARTIAL if StepStatus.SUCCESS in statuses else WorkflowStatus.FAILED
        else:
            result.status = WorkflowStatus.SUCCESS

    async def _execute_step(self, step: WorkflowStep, completed: dict[str, Any]) -> StepResult:
        if step.condition:
            try:
                cond_result = eval(step.condition, {"__builtins__": {}}, {"completed": completed})  # noqa: S307
                if not cond_result:
                    return StepResult(step_id=step.id, status=StepStatus.SKIPPED)
            except Exception as exc:
                return StepResult(step_id=step.id, status=StepStatus.FAILED, error=f"Condition error: {exc}")

        for attempt in range(step.max_retries + 1):
            start = time.time()
            try:
                handler = step.handler or self._step_handlers.get(step.name)
                if handler is None:
                    return StepResult(step_id=step.id, status=StepStatus.FAILED, error=f"No handler for {step.name}")

                output = await asyncio.wait_for(
                    handler(**step.params, **{k: completed.get(k) for k in step.depends_on}),
                    timeout=step.timeout,
                )
                return StepResult(step_id=step.id, status=StepStatus.SUCCESS, output=output, duration=time.time() - start)
            except Exception as exc:
                logger.warning("Step {} attempt {}/{} failed: {}", step.id, attempt + 1, step.max_retries + 1, exc)
                if attempt < step.max_retries:
                    await asyncio.sleep(step.retry_delay * (2 ** attempt))
                else:
                    return StepResult(step_id=step.id, status=StepStatus.FAILED, error=str(exc), duration=time.time() - start)

        return StepResult(step_id=step.id, status=StepStatus.FAILED, error="Max retries exceeded")

    def get_result(self, workflow_id: str) -> WorkflowResult | None:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> list[dict[str, Any]]:
        return [
            {"id": wid, "status": wr.status.value, "steps": len(wr.steps),
             "duration": wr.end_time - wr.start_time if wr.end_time else 0}
            for wid, wr in self._workflows.items()
        ]

    # ---- Visualization exports -----------------------------------------------

    def export_to_d3(self, workflow_id: str) -> dict[str, Any]:
        steps = self._workflow_steps.get(workflow_id)
        result = self._workflows.get(workflow_id)
        if steps is None:
            return {"nodes": [], "links": []}

        step_statuses: dict[str, str] = {}
        if result:
            for sid, sr in result.steps.items():
                step_statuses[sid] = sr.status.value

        nodes = [
            {
                "id": s.id,
                "label": s.name,
                "status": step_statuses.get(s.id, "pending"),
            }
            for s in steps
        ]
        links = [
            {
                "source": dep,
                "target": s.id,
                "label": "depends_on",
            }
            for s in steps
            for dep in s.depends_on
        ]
        return {"nodes": nodes, "links": links}

    def export_to_react_flow(self, workflow_id: str) -> dict[str, Any]:
        steps = self._workflow_steps.get(workflow_id)
        result = self._workflows.get(workflow_id)
        if steps is None:
            return {"nodes": [], "edges": []}

        step_statuses: dict[str, str] = {}
        if result:
            for sid, sr in result.steps.items():
                step_statuses[sid] = sr.status.value

        level_map: dict[str, int] = {}
        for s in steps:
            if not s.depends_on:
                level_map[s.id] = 0
            else:
                level_map[s.id] = max(level_map.get(d, 0) for d in s.depends_on) + 1

        levels: dict[int, int] = {}
        for _sid, lvl in level_map.items():
            levels[lvl] = levels.get(lvl, 0) + 1

        node_counters: dict[int, int] = {}
        nodes = []
        for s in steps:
            lvl = level_map.get(s.id, 0)
            node_counters[lvl] = node_counters.get(lvl, 0) + 1
            x = 250 * lvl + 50
            count_in_level = levels.get(lvl, 1)
            idx = node_counters[lvl]
            y = 150 * idx - (150 * count_in_level) // 2 + 75
            nodes.append({
                "id": s.id,
                "type": "default",
                "position": {"x": x, "y": y},
                "data": {
                    "label": s.name,
                    "status": step_statuses.get(s.id, "pending"),
                    "condition": s.condition,
                    "retries": s.max_retries,
                },
            })

        edges = [
            {
                "id": f"{dep}-{s.id}",
                "source": dep,
                "target": s.id,
                "label": "",
            }
            for s in steps
            for dep in s.depends_on
        ]
        return {"nodes": nodes, "edges": edges}

    def export_workflow_dag(self, workflow_id: str) -> list[dict[str, Any]]:
        steps = self._workflow_steps.get(workflow_id)
        result = self._workflows.get(workflow_id)
        if steps is None:
            return []

        step_statuses: dict[str, str] = {}
        step_outputs: dict[str, Any] = {}
        step_errors: dict[str, str | None] = {}
        if result:
            for sid, sr in result.steps.items():
                step_statuses[sid] = sr.status.value
                step_outputs[sid] = sr.output
                step_errors[sid] = sr.error

        return [
            {
                "id": s.id,
                "name": s.name,
                "depends_on": s.depends_on,
                "condition": s.condition,
                "max_retries": s.max_retries,
                "timeout": s.timeout,
                "params": s.params,
                "status": step_statuses.get(s.id, "pending"),
                "output": step_outputs.get(s.id),
                "error": step_errors.get(s.id),
            }
            for s in steps
        ]

    # ---- Workflow templates --------------------------------------------------

    def save_template(self, name: str, steps: list[WorkflowStep]) -> str:
        if _TEMPLATE_DIR:
            template_path = _TEMPLATE_DIR / f"{name}.json"
        else:
            template_path = Path(f"{name}.json")

        data = [
            {
                "id": s.id,
                "name": s.name,
                "depends_on": s.depends_on,
                "condition": s.condition,
                "max_retries": s.max_retries,
                "retry_delay": s.retry_delay,
                "timeout": s.timeout,
                "params": s.params,
            }
            for s in steps
        ]
        template_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Workflow template saved: {}", template_path)
        return str(template_path)

    def load_template(self, name: str) -> list[WorkflowStep]:
        if _TEMPLATE_DIR:
            template_path = _TEMPLATE_DIR / f"{name}.json"
        else:
            template_path = Path(f"{name}.json")

        if not template_path.exists():
            raise FileNotFoundError(f"Workflow template not found: {template_path}")

        data = json.loads(template_path.read_text(encoding="utf-8"))
        steps = [
            WorkflowStep(
                id=item["id"],
                name=item["name"],
                depends_on=item.get("depends_on", []),
                condition=item.get("condition"),
                max_retries=item.get("max_retries", 0),
                retry_delay=item.get("retry_delay", 1.0),
                timeout=item.get("timeout", 300.0),
                params=item.get("params", {}),
            )
            for item in data
        ]
        logger.info("Workflow template loaded: {} ({} steps)", template_path, len(steps))
        return steps


    def health_check(self) -> dict[str, Any]:
        """Returns health status: uptime proxy via active workflows, engine state."""
        total = len(self._workflows)
        running = sum(1 for w in self._workflows.values() if w.status == WorkflowStatus.RUNNING)
        failed = sum(1 for w in self._workflows.values() if w.status == WorkflowStatus.FAILED)
        return {
            "status": "healthy" if failed == 0 or total == 0 else "degraded",
            "workflows_total": total,
            "workflows_running": running,
            "workflows_failed": failed,
            "handlers_registered": len(self._step_handlers),
            "healthy": failed == 0 or total == 0,
        }


_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine

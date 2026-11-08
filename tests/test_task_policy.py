"""The operator's tool switches on the task path.

Measured before the gate existed: `raven task run` built the full 197-tool registry and
`TaskRunner` passed only a subject role to `ToolRegistry.call`, so a planner step named
`shell` or `python` - both in `_DEFAULT_TOOLS_DENY` - ran, and 54 exec-class tools ignored
`EXEC_SECURITY=deny`. The web and Telegram `/task` path is a different control (its registry
strips exec-class tools) and is asserted here too, because both are documented.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

from raven.core.config import _DEFAULT_TOOLS_DENY, settings
from raven.core.task_engine.models import Task, TaskStatus, TaskStep
from raven.core.task_engine.runner import TaskRunner
from raven.core.task_engine.store import TaskStore
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

RAN: list[str] = []


@pytest.fixture
async def store(tmp_path):
    s = TaskStore(str(tmp_path / "tasks.db"))
    yield s
    await s.close()


@pytest.fixture
def switches(monkeypatch):
    RAN.clear()
    monkeypatch.setattr(settings, "tools_allow", "")
    monkeypatch.setattr(settings, "exec_ask_mode", "always")
    monkeypatch.setattr(settings, "workspace_only", False)


def _registry(name: str, *, dangerous: bool = False) -> ToolRegistry:
    def _handler(**kwargs):
        RAN.append(name)
        return f"ran:{name}"

    registry = ToolRegistry()
    registry.register(
        ToolSpec(name=name, description=f"policy probe {name}", parameters={}, handler=_handler, dangerous=dangerous)
    )
    return registry


def _task(tool: str, **kwargs) -> Task:
    task = Task(goal="policy probe", **kwargs)
    task.steps = [TaskStep(task_id="", order=0, description="d", tool=tool, params={})]
    for step in task.steps:
        step.task_id = task.id
    return task


async def _finish(runner: TaskRunner, task: Task):
    await runner.submit(task)
    done = await runner.wait(task.id, timeout=10)
    assert done is not None
    return done


async def test_a_default_denied_step_is_refused_before_the_handler(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    runner = TaskRunner(store, _registry("nodes_list"))
    done = await _finish(runner, _task("nodes_list"))
    assert done.status is TaskStatus.FAILED
    assert "TOOLS_DENY" in (done.error or ""), done.error
    assert RAN == []


async def test_an_exec_class_step_is_refused_when_nobody_can_confirm(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    runner = TaskRunner(store, _registry("git_push"))
    done = await _finish(runner, _task("git_push"))
    assert done.status is TaskStatus.FAILED
    assert "operator policy" in (done.error or ""), done.error
    assert RAN == []


async def test_a_confirmer_that_says_yes_lets_the_step_run(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "ask")

    async def approve(tool_name: str, arguments: dict[str, Any]) -> bool:
        return True

    runner = TaskRunner(store, _registry("git_push"), confirm_fn=approve)
    done = await _finish(runner, _task("git_push"))
    assert done.status is TaskStatus.COMPLETED, done.error
    assert RAN == ["git_push"]


async def test_a_confirmer_that_says_no_stops_it(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "ask")

    async def refuse(tool_name: str, arguments: dict[str, Any]) -> bool:
        return False

    runner = TaskRunner(store, _registry("git_push"), confirm_fn=refuse)
    done = await _finish(runner, _task("git_push"))
    assert done.status is TaskStatus.FAILED
    assert RAN == []


async def test_exec_security_full_never_prompts(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "full")

    async def must_not_be_called(tool_name: str, arguments: dict[str, Any]) -> bool:
        raise AssertionError("EXEC_SECURITY=full must not ask")

    runner = TaskRunner(store, _registry("git_push"), confirm_fn=must_not_be_called)
    done = await _finish(runner, _task("git_push"))
    assert done.status is TaskStatus.COMPLETED, done.error


async def test_a_plain_step_still_runs_under_the_shipped_defaults(store, switches, monkeypatch) -> None:
    monkeypatch.setattr(settings, "exec_security", "deny")
    runner = TaskRunner(store, _registry("file_read"))
    done = await _finish(runner, _task("file_read"))
    assert done.status is TaskStatus.COMPLETED, done.error
    assert RAN == ["file_read"]


async def test_the_refusal_is_recorded_once_not_retried(store, switches, monkeypatch) -> None:
    """A policy refusal is permanent; retrying it three times would only delay the answer."""
    monkeypatch.setattr(settings, "exec_security", "deny")
    runner = TaskRunner(store, _registry("git_push"))
    done = await _finish(runner, _task("git_push"))
    assert done.steps[0].error is not None and done.steps[0].error.count("operator policy") == 1


async def test_the_runner_builds_the_policy_every_other_surface_builds(store, switches) -> None:
    runner = TaskRunner(store, _registry("file_read"))
    assert runner._tool_policy.profile == "full"
    assert runner._tool_policy._deny == {name for name in _DEFAULT_TOOLS_DENY}


async def test_the_web_and_telegram_task_registry_strips_every_exec_class_tool(store, switches) -> None:
    from raven.core.security.tool_policy import is_exec_class
    from raven.tools.register_all import create_task_tool_registry

    registry = create_task_tool_registry()
    left = sorted(spec.name for spec in registry.list() if is_exec_class(spec.name))
    assert left == [], left


def test_the_cli_wires_a_confirmer_into_the_runners_that_execute_steps() -> None:
    source = pathlib.Path("raven/cli/task_cmd.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    executed = 0
    plain = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "TaskRunner":
            if any(kw.arg == "confirm_fn" for kw in node.keywords):
                executed += 1
            else:
                plain += 1
    assert executed == 2, executed
    assert plain == 1, plain
    assert "terminal_confirm" in source


def test_the_documented_surface_list_includes_the_task_path() -> None:
    doc = pathlib.Path("docs/configuration.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| `EXEC_SECURITY`"))
    for surface in ("agent path", "orchestrator", "task steps", "MCP"):
        assert surface in row, (surface, row)
    example = pathlib.Path(".env.example").read_text(encoding="utf-8")
    assert "task steps" in example

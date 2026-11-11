from __future__ import annotations

import ast
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from raven.core.task_engine.planner import PlanValidationError, TaskPlanner
from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.register_all import create_task_tool_registry

LF = chr(10)
ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "raven/core/task_engine/planner.py"
TASK_CMD = ROOT / "raven/cli/task_cmd.py"


class _Stream:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def complete_stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield self._payload

        return _gen()


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="file_read",
            description="read a file",
            parameters={"path": {"type": "string", "required": True, "description": "the file to read"}},
            handler=_noop,
            category="file",
        )
    )
    registry.register(
        ToolSpec(
            name="web_search",
            description="search the web",
            parameters={"query": {"type": "string", "required": True}},
            handler=_noop,
            category="web",
        )
    )
    return registry


async def _noop(**kwargs: Any) -> str:
    return "ok"


def _plan(steps: list[dict[str, Any]]) -> str:
    return json.dumps({"summary": "a plan", "steps": steps})


async def _plan_from(steps: list[dict[str, Any]], registry: ToolRegistry | None = None) -> Any:
    planner = TaskPlanner(registry or _registry())
    return await planner.plan("do the thing", _Stream(_plan(steps)))  # type: ignore[arg-type]


async def test_a_step_naming_a_tool_that_does_not_exist_is_rejected() -> None:
    with pytest.raises(PlanValidationError, match="does not serve"):
        await _plan_from(
            [
                {"description": "read", "tool": "file_read", "params": {}},
                {"description": "ghost", "tool": "teleport", "params": {}},
            ]
        )


async def test_the_rejection_names_the_step_and_the_tool() -> None:
    with pytest.raises(PlanValidationError) as excinfo:
        await _plan_from([{"description": "ghost", "tool": "teleport", "params": {}}])
    assert "step 1" in str(excinfo.value)
    assert "teleport" in str(excinfo.value)


async def test_a_step_without_a_tool_name_is_rejected_too() -> None:
    for bad in ("", None):
        with pytest.raises(PlanValidationError) as excinfo:
            await _plan_from([{"description": "no tool", "tool": bad, "params": {}}])
        assert "no tool named" in str(excinfo.value)


async def test_a_valid_plan_is_unchanged() -> None:
    task = await _plan_from(
        [
            {"description": "read it", "tool": "file_read", "params": {"path": "a.txt"}},
            {"description": "search it", "tool": "web_search", "params": {"query": "a"}},
        ]
    )
    assert [s.tool for s in task.steps] == ["file_read", "web_search"]
    assert [s.order for s in task.steps] == [0, 1]
    assert task.steps[0].params == {"path": "a.txt"}


async def test_the_gate_is_the_registry_the_planner_was_given() -> None:
    # shell is registered in the full registry and stripped from the narrowed task one: the check
    # follows the registry the planner was handed, not a hard-coded list.
    full = create_task_tool_registry()
    full.register(
        ToolSpec(name="shell", description="run a command", parameters={"cmd": {"type": "string"}}, handler=_noop)
    )
    task = await _plan_from([{"description": "run", "tool": "shell", "params": {}}], full)
    assert task.steps[0].tool == "shell"
    with pytest.raises(PlanValidationError):
        await _plan_from([{"description": "run", "tool": "shell", "params": {}}], create_task_tool_registry())


# --- the prompt the plan is written against -------------------------------------------------------


def test_the_prompt_lists_every_registered_tool() -> None:
    registry = _registry()
    prompt = TaskPlanner(registry)._build_prompt("goal")
    for spec in registry.list():
        assert f"- {spec.name}: " in prompt, spec.name


def test_a_tool_added_to_the_registry_appears_without_editing_the_planner() -> None:
    registry = _registry()
    registry.register(
        ToolSpec(name="new_thing", description="does new things", parameters={}, handler=_noop, category="file")
    )
    assert "- new_thing: does new things" in TaskPlanner(registry)._build_prompt("goal")


def test_the_prompt_keeps_param_names_types_and_required_flags() -> None:
    prompt = TaskPlanner(_registry())._build_prompt("goal")
    assert "path:string!" in prompt, prompt[prompt.index("file_read") : prompt.index("file_read") + 200]
    assert "query:string!" in prompt


def test_the_prompt_drops_the_per_parameter_prose() -> None:
    # The schema's own description text is what made this block 54,087 characters for 197 tools.
    prompt = TaskPlanner(_registry())._build_prompt("goal")
    assert "the file to read" not in prompt


def test_the_compact_form_is_measurably_smaller_than_the_schema_dump() -> None:
    registry = create_task_tool_registry()
    prompt = TaskPlanner(registry)._build_prompt("goal")
    json_form = "\n".join(f"- {t.name}: {t.description} (params: {json.dumps(t.parameters)})" for t in registry.list())
    assert len(prompt) < len(json_form) * 0.6, f"{len(prompt)} vs {len(json_form)}"


def test_the_planner_no_longer_dumps_parameter_schemas() -> None:
    source = PLANNER.read_text(encoding="utf-8")
    assert "json.dumps(t.parameters)" not in source


# --- the operator sees the rejection -------------------------------------------------------------


def test_task_run_reports_a_rejected_plan_instead_of_tracing_back() -> None:
    tree = ast.parse(TASK_CMD.read_text(encoding="utf-8"))
    handler = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and isinstance(n.type, ast.Name) and n.type.id == "PlanValidationError"
    ]
    assert len(handler) == 1, "the CLI must catch the rejection exactly once"
    printed = [n for n in ast.walk(handler[0]) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "print"]
    assert printed, "the rejection must be shown, not swallowed"


def test_plan_validation_error_is_a_valueerror() -> None:
    # Every caller already handles a planning failure as an Exception; a ValueError keeps it that way.
    assert issubclass(PlanValidationError, ValueError)


def test_the_pinned_plan_shape_still_parses() -> None:
    steps = re.findall(r'"tool":\s*"([^"]+)"', PLANNER.read_text(encoding="utf-8"))
    assert steps == ["tool_name"], "the output example in PLANNER_PROMPT drifted"

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from raven.core.workflow.models import TemplateCategory, TemplateStep, TemplateTrigger, WorkflowTemplate
from raven.core.workflow.runner import TemplateRunner, _apply_schema_defaults


def _template(**overrides: Any) -> WorkflowTemplate:
    base: dict[str, Any] = dict(
        id="tpl-1",
        name="Daily Digest",
        description="desc",
        category=TemplateCategory.DAILY,
        trigger=TemplateTrigger.MANUAL,
    )
    base.update(overrides)
    return WorkflowTemplate(**base)


def _runner() -> SimpleNamespace:
    return SimpleNamespace(submit=AsyncMock(), store=SimpleNamespace(), tools=SimpleNamespace())


class _PlannerStub:
    def __init__(self, plan: Any) -> None:
        self.plan = plan


def test_apply_schema_defaults_fills_missing_and_keeps_present() -> None:
    schema = {"properties": {"a": {"default": 1}, "b": {}, "c": {"default": 3}}}
    assert _apply_schema_defaults(None, schema) == {"a": 1, "c": 3}
    assert _apply_schema_defaults({"a": 9}, schema) == {"a": 9, "c": 3}
    assert _apply_schema_defaults({"c": 0}, schema) == {"a": 1, "c": 0}  # present falsy kept


@pytest.mark.asyncio
async def test_instantiate_uses_predefined_steps() -> None:
    runner = _runner()
    tr = TemplateRunner(runner, runner.store, runner.tools, llm=None)  # type: ignore[arg-type]
    tpl = _template(
        steps_goal="Do {thing}",
        config_schema={"properties": {"thing": {"default": "X"}}},
        predefined_steps=[TemplateStep(description="first", tool="web", params={"q": "1"})],
    )
    task_id = await tr.instantiate(tpl, user_id="u", channel="tg")
    task = runner.submit.await_args.args[0]
    assert task_id == task.id
    assert task.goal == "Do X"
    assert task.metadata["template_id"] == "tpl-1"
    assert task.metadata["config"] == {"thing": "X"}
    assert len(task.steps) == 1
    assert task.steps[0].description == "first"
    assert task.steps[0].tool == "web"


@pytest.mark.asyncio
async def test_instantiate_invalid_config_raises_valueerror() -> None:
    runner = _runner()
    tr = TemplateRunner(runner, runner.store, runner.tools, llm=None)  # type: ignore[arg-type]
    tpl = _template(steps_goal="Need {missing}", predefined_steps=[TemplateStep(description="x")])
    with pytest.raises(ValueError, match="Invalid config"):
        await tr.instantiate(tpl)
    runner.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_instantiate_uses_planner_when_llm_present(monkeypatch: pytest.MonkeyPatch) -> None:
    planned = SimpleNamespace(steps=["planned-step"], plan_summary="summary")
    fake_planner = _PlannerStub(AsyncMock(return_value=planned))
    monkeypatch.setattr("raven.core.task_engine.planner.TaskPlanner", lambda tools: fake_planner)
    runner = _runner()
    tr = TemplateRunner(runner, runner.store, runner.tools, llm=object())  # type: ignore[arg-type]
    tpl = _template(description="run the thing")
    task_id = await tr.instantiate(tpl)
    task = runner.submit.await_args.args[0]
    assert task.steps == ["planned-step"]
    assert task.plan_summary == "summary"
    assert task_id == task.id
    fake_planner.plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_instantiate_planner_failure_raises_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_planner = _PlannerStub(AsyncMock(side_effect=TimeoutError("llm down")))
    monkeypatch.setattr("raven.core.task_engine.planner.TaskPlanner", lambda tools: fake_planner)
    runner = _runner()
    tr = TemplateRunner(runner, runner.store, runner.tools, llm=object())  # type: ignore[arg-type]
    tpl = _template(description="goal")
    with pytest.raises(RuntimeError, match="planning failed"):
        await tr.instantiate(tpl)


@pytest.mark.asyncio
async def test_instantiate_no_steps_and_no_llm_raises() -> None:
    runner = _runner()
    tr = TemplateRunner(runner, runner.store, runner.tools, llm=None)  # type: ignore[arg-type]
    tpl = _template(description="goal", predefined_steps=[])
    with pytest.raises(ValueError, match="no predefined steps"):
        await tr.instantiate(tpl)


@pytest.mark.asyncio
async def test_schedule_as_routine_engine_path(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []

    async def add_routine(routine) -> None:
        added.append(routine)

    monkeypatch.setattr("raven.core.routine.engine.get_routine_engine", lambda: SimpleNamespace(add_routine=add_routine))
    tpl = _template(
        trigger=TemplateTrigger.INTERVAL,
        default_interval=3600,
    )
    rid = await TemplateRunner.schedule_as_routine(tpl, user_id="sys", channel="internal")
    assert added and added[0].id == rid
    assert added[0].schedule == "3600"
    assert added[0].trigger.value == "interval"


@pytest.mark.asyncio
async def test_schedule_as_routine_defaults_schedule_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    added: list[Any] = []

    async def add_routine(routine) -> None:
        added.append(routine)

    monkeypatch.setattr("raven.core.routine.engine.get_routine_engine", lambda: SimpleNamespace(add_routine=add_routine))
    tpl = _template(trigger=TemplateTrigger.MANUAL)
    await TemplateRunner.schedule_as_routine(tpl)
    assert added[0].schedule == "08:00"
    assert added[0].trigger.value == "manual"


@pytest.mark.asyncio
async def test_schedule_as_routine_store_path(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[Any] = []
    started: list[Any] = []

    class _FakeStore:
        def __init__(self, db_path: str) -> None:
            self.db_path = db_path

        async def save_routine(self, routine) -> None:
            saved.append(routine)

        async def delete_routine(self, rid: str) -> None:
            saved.remove(rid)

    class _FakeEngine:
        def __init__(self, store) -> None:
            self._store = store

        async def start(self) -> None:
            started.append(self)

    monkeypatch.setattr("raven.core.routine.engine.get_routine_engine", lambda: None)
    monkeypatch.setattr("raven.core.routine.store.RoutineStore", _FakeStore)
    monkeypatch.setattr("raven.core.routine.engine.RoutineEngine", _FakeEngine)
    tpl = _template(trigger=TemplateTrigger.SCHEDULED, default_schedule="07:30")
    rid = await TemplateRunner.schedule_as_routine(tpl, db_path="data/x.db")
    assert rid == saved[0].id
    assert saved[0].schedule == "07:30"
    assert started  # engine started


@pytest.mark.asyncio
async def test_schedule_as_routine_store_rolls_back_on_start_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _FakeStore:
        def __init__(self, db_path: str) -> None:
            pass

        async def save_routine(self, routine) -> None:
            events.append("save")

        async def delete_routine(self, rid: str) -> None:
            events.append("delete")

    class _FakeEngine:
        def __init__(self, store) -> None:
            pass

        async def start(self) -> None:
            raise RuntimeError("engine failed")

    monkeypatch.setattr("raven.core.routine.engine.get_routine_engine", lambda: None)
    monkeypatch.setattr("raven.core.routine.store.RoutineStore", _FakeStore)
    monkeypatch.setattr("raven.core.routine.engine.RoutineEngine", _FakeEngine)
    tpl = _template(trigger=TemplateTrigger.INTERVAL, default_interval=60)
    with pytest.raises(RuntimeError, match="engine failed"):
        await TemplateRunner.schedule_as_routine(tpl, db_path="data/x.db")
    assert events == ["save", "delete"]

from __future__ import annotations

import asyncio

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.core.workflow.templates import BUILTIN_TEMPLATES
from raven.tools import workflow as wf_mod

_VALID_ID = BUILTIN_TEMPLATES[0].id
_VALID_CATEGORY = BUILTIN_TEMPLATES[0].category.value


class TestWorkflowListAndGet:
    def test_list_all(self) -> None:
        out = wf_mod.workflow_list_templates()
        assert out.startswith("- **")
        assert _VALID_ID in out

    def test_list_by_category(self) -> None:
        out = wf_mod.workflow_list_templates(_VALID_CATEGORY)
        assert _VALID_ID in out

    def test_list_unknown_category(self) -> None:
        assert wf_mod.workflow_list_templates("__nope__") == "No templates found."

    def test_list_categories(self) -> None:
        out = wf_mod.workflow_list_categories()
        assert out.startswith("Categories:")
        assert _VALID_CATEGORY in out

    def test_get_template_detail(self) -> None:
        out = wf_mod.workflow_get_template(_VALID_ID)
        assert out.startswith(f"**{BUILTIN_TEMPLATES[0].name}**")
        assert "Config parameters:" in out
        assert "Goal:" in out

    def test_get_template_not_found(self) -> None:
        assert wf_mod.workflow_get_template("__ghost__") == "Template '__ghost__' not found."


class TestWorkflowInstantiate:
    @pytest.mark.asyncio
    async def test_invalid_json(self) -> None:
        assert (await wf_mod.workflow_instantiate(_VALID_ID, "not json")).startswith("Invalid config JSON:")

    @pytest.mark.asyncio
    async def test_template_not_found(self) -> None:
        out = await wf_mod.workflow_instantiate("__ghost__", "{}")
        assert out == "Template '__ghost__' not found."

    @pytest.mark.asyncio
    async def test_success_and_completion_callback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        class _FakeStore:
            def __init__(self, *_a: object) -> None:
                self.closed = 0

            async def close(self) -> None:
                self.closed += 1

        class _FakeRunner:
            def __init__(self, store: _FakeStore, _tools: object) -> None:
                self.store = store
                captured["runner"] = self

            def on_complete(self, _task_id: str, fn: object) -> None:
                self.fn = fn

        class _FakeTplRunner:
            def __init__(self, runner: _FakeRunner, store: _FakeStore, _t: object, _x: object) -> None:
                self.runner = runner
                self.store = store

            async def instantiate(self, template: object, user_id: str, channel: str, config: object) -> str:
                return "task-XYZ"

        monkeypatch.setattr("raven.core.task_engine.store.TaskStore", _FakeStore)
        monkeypatch.setattr("raven.core.task_engine.runner.TaskRunner", _FakeRunner)
        monkeypatch.setattr("raven.core.workflow.runner.TemplateRunner", _FakeTplRunner)
        monkeypatch.setattr("raven.tools.register_all.create_tool_registry", lambda: {})

        out = await wf_mod.workflow_instantiate(_VALID_ID, '{"a": 1}')
        assert out == f"Instantiated '{BUILTIN_TEMPLATES[0].name}' as task `task-XYZ`."
        runner = captured["runner"]
        assert runner is not None
        # fire the completion callback that closes the store
        cast_fn = runner.fn  # type: ignore[attr-defined]
        cast_fn()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert runner.store.closed >= 1  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_instantiate_error_closes_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stores: list[object] = []

        class _FakeStore:
            def __init__(self, *_a: object) -> None:
                self.closed = 0
                stores.append(self)

            async def close(self) -> None:
                self.closed += 1

        class _FakeRunner:
            def __init__(self, *_a: object) -> None:
                return None

            def on_complete(self, *_a: object) -> None:
                return None

        class _FakeTplRunner:
            def __init__(self, *_a: object) -> None:
                return None

            async def instantiate(self, *_a: object, **_k: object) -> str:
                raise RuntimeError("boom")

        monkeypatch.setattr("raven.core.task_engine.store.TaskStore", _FakeStore)
        monkeypatch.setattr("raven.core.task_engine.runner.TaskRunner", _FakeRunner)
        monkeypatch.setattr("raven.core.workflow.runner.TemplateRunner", _FakeTplRunner)
        monkeypatch.setattr("raven.tools.register_all.create_tool_registry", lambda: {})

        out = await wf_mod.workflow_instantiate(_VALID_ID, "{}")
        assert out == "Failed to instantiate: boom"
        assert stores and stores[0].closed == 1  # type: ignore[attr-defined]


class TestWorkflowSchedule:
    @pytest.mark.asyncio
    async def test_invalid_json(self) -> None:
        assert (await wf_mod.workflow_schedule(_VALID_ID, "{bad")).startswith("Invalid config JSON:")

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        assert await wf_mod.workflow_schedule("__ghost__", "{}") == "Template '__ghost__' not found."

    @pytest.mark.asyncio
    async def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _sched(**_k: object) -> str:
            return "routine-9"

        monkeypatch.setattr("raven.core.workflow.runner.TemplateRunner.schedule_as_routine", _sched)
        out = await wf_mod.workflow_schedule(_VALID_ID, "{}")
        assert out == f"Scheduled '{BUILTIN_TEMPLATES[0].name}' as routine `routine-9`."

    @pytest.mark.asyncio
    async def test_schedule_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _sched(**_k: object) -> str:
            raise ValueError("nope")

        monkeypatch.setattr("raven.core.workflow.runner.TemplateRunner.schedule_as_routine", _sched)
        assert await wf_mod.workflow_schedule(_VALID_ID, "{}") == "Failed to schedule: nope"


class TestRegistration:
    def test_registers_five_tools(self) -> None:
        registry = ToolRegistry()
        wf_mod.register_workflow_tools(registry)
        for name in (
            "workflow_list_templates",
            "workflow_list_categories",
            "workflow_get_template",
            "workflow_instantiate",
            "workflow_schedule",
        ):
            assert registry.get(name) is not None

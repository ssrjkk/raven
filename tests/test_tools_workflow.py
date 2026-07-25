# mypy: ignore-errors
from __future__ import annotations

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry
from raven.tools.workflow import (
    register_workflow_tools,
    workflow_get_template,
    workflow_list_categories,
    workflow_list_templates,
)


class TestWorkflowTools:
    def test_list_templates(self) -> None:
        result = workflow_list_templates()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_list_templates_by_category(self) -> None:
        result = workflow_list_templates(category="daily")
        assert isinstance(result, str)

    def test_list_templates_unknown_category(self) -> None:
        result = workflow_list_templates(category="nonexistent")
        assert result == "No templates found."

    def test_list_categories(self) -> None:
        result = workflow_list_categories()
        assert "daily" in result.lower()
        assert "dev" in result.lower()

    def test_get_template_found(self) -> None:
        result = workflow_get_template("morning-briefing")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_template_not_found(self) -> None:
        result = workflow_get_template("nonexistent-template-id")
        assert "not found" in result

    def test_register_tools(self) -> None:
        registry = ToolRegistry()
        register_workflow_tools(registry)
        for name in ("workflow_list_templates", "workflow_list_categories", "workflow_get_template", "workflow_instantiate", "workflow_schedule"):
            assert registry.get(name) is not None

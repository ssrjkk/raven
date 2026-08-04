from __future__ import annotations

import pytest


class TestBuildArgumentsSchema:
    def test_build_schema_marks_required(self):
        from raven.core.agents.validation import build_arguments_schema

        schema = build_arguments_schema(
            {"path": {"type": "string", "required": True}, "mode": {"type": "string", "required": False}}
        )
        assert schema["type"] == "object"
        assert schema["required"] == ["path"]
        assert schema["additionalProperties"] is False

    def test_build_schema_no_required(self):
        from raven.core.agents.validation import build_arguments_schema

        schema = build_arguments_schema({"a": {"type": "integer"}})
        assert schema["required"] == []

    def test_build_schema_ignores_non_mapping_specs(self):
        from raven.core.agents.validation import build_arguments_schema

        schema = build_arguments_schema({"a": {"type": "string", "required": True}, "b": "not-a-spec"})
        assert schema["required"] == ["a"]


class TestValidateToolArguments:
    def test_valid_arguments_return_none(self):
        from raven.core.agents.validation import validate_tool_arguments

        error = validate_tool_arguments("echo", {"text": {"type": "string", "required": True}}, {"text": "hi"})
        assert error is None

    def test_missing_required_argument(self):
        from raven.core.agents.validation import validate_tool_arguments

        error = validate_tool_arguments("echo", {"text": {"type": "string", "required": True}}, {})
        assert error is not None
        assert "echo" in error
        assert "text" in error

    def test_extra_unknown_property(self):
        from raven.core.agents.validation import validate_tool_arguments

        error = validate_tool_arguments("echo", {"text": {"type": "string"}}, {"text": "hi", "surprise": 1})
        assert error is not None
        assert "surprise" in error

    def test_wrong_type(self):
        from raven.core.agents.validation import validate_tool_arguments

        error = validate_tool_arguments("count", {"n": {"type": "integer"}}, {"n": "not-a-number"})
        assert error is not None

    def test_nested_parameter_path_in_error(self):
        from raven.core.agents.validation import validate_tool_arguments

        parameters = {"config": {"type": "object", "properties": {"name": {"type": "string"}}}}
        error = validate_tool_arguments("configure", parameters, {"config": {"name": 42}})
        assert error is not None
        assert "config" in error


class TestSchemaRoundTripWithRegistry:
    def test_registry_spec_parameters_validate_correctly(self):
        from raven.core.agents.validation import validate_tool_arguments
        from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name="write",
                description="write file",
                parameters={"path": {"type": "string", "required": True}, "content": {"type": "string", "required": False}},
                handler=lambda path, content="": content,
                category="file",
            )
        )
        spec = registry.get("write")
        assert spec is not None
        assert validate_tool_arguments("write", spec.parameters, {"path": "a.txt"}) is None
        assert validate_tool_arguments("write", spec.parameters, {"content": "x"}) is not None

    @pytest.mark.parametrize(
        ("params", "args"),
        [
            ({"x": {"type": "integer"}}, {"x": 3}),
            ({"x": {"type": "integer"}, "y": {"type": "string", "required": True}}, {"y": "a"}),
            ({}, {}),
        ],
    )
    def test_valid_cases(self, params, args):
        from raven.core.agents.validation import validate_tool_arguments

        assert validate_tool_arguments("t", params, args) is None

from __future__ import annotations

from collections.abc import Mapping

from jsonschema import Draft7Validator


def build_arguments_schema(parameters: Mapping[str, object]) -> dict[str, object]:
    """Build a JSON Schema object description from tool parameter metadata."""
    required: list[str] = []
    for name, spec in parameters.items():
        if isinstance(spec, Mapping) and spec.get("required"):
            required.append(name)
    return {
        "type": "object",
        "properties": dict(parameters),
        "required": required,
        "additionalProperties": False,
    }


def validate_tool_arguments(
    tool_name: str,
    parameters: Mapping[str, object],
    arguments: Mapping[str, object],
) -> str | None:
    """Validate tool arguments against the JSON Schema described by `parameters`.

    Returns a human-readable error string when validation fails, otherwise None.
    The tool handler is never invoked for invalid arguments.
    """
    schema = build_arguments_schema(parameters)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return None
    first = errors[0]
    where = ".".join(str(part) for part in first.path) or "(root)"
    return f"Invalid arguments for '{tool_name}' at '{where}': {first.message}"

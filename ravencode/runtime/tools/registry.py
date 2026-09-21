from __future__ import annotations

import contextvars
import functools
from typing import Any

from loguru import logger

from raven.core.agents.validation import validate_tool_arguments
from ravencode.core.metrics import observe_tool
from ravencode.runtime.question import QuestionError

from .definitions import (
    _PLAN_MODE_DENIED,
    MODULE_TOOLS,
)
from .sandbox_policy import _sandbox_deny_reason

_plugin_tools_loaded = False




def _ensure_plugin_tools() -> None:
    global _plugin_tools_loaded
    if not _plugin_tools_loaded:
        try:
            from ravencode.runtime.plugins import get_plugin_registry

            reg = get_plugin_registry()
            for name, tool in reg.all_tools().items():
                if name not in MODULE_TOOLS:
                    MODULE_TOOLS[name] = tool
            _plugin_tools_loaded = True
        except ImportError:
            logger.debug("plugin tools unavailable, skipping")




def get_tool_definitions(plan_mode: bool = False) -> list[dict[str, Any]]:
    _ensure_plugin_tools()
    return list(_build_tool_definitions(plan_mode))




@functools.lru_cache(maxsize=2)
def _build_tool_definitions(plan_mode: bool) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in MODULE_TOOLS.values()
        if not plan_mode or t["name"] not in _PLAN_MODE_DENIED
    )




def is_dangerous(name: str) -> bool:
    t = MODULE_TOOLS.get(name)
    return bool(t.get("dangerous")) if t else False




@observe_tool(tool_name="execute_tool")
async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    _ensure_plugin_tools()
    tool = MODULE_TOOLS.get(name)
    if not tool:
        return f"[error] unknown tool: {name}"
    validation_error = validate_tool_arguments(name, tool.get("parameters", {}), arguments)
    if validation_error is not None:
        logger.warning("Tool call to '{}' rejected: {}", name, validation_error)
        return f"[validation_error] Invalid arguments for '{name}': {validation_error}. Fix your JSON and try again."
    perm = _get_permission_for_tool(name, arguments)
    if not perm[0]:
        return f"[denied] {perm[1]}"
    try:
        result = await tool["handler"](**arguments)
        if isinstance(result, list):
            result_str = "\n".join(str(r) for r in result[:200])
        else:
            result_str = str(result)
        if len(result_str) > 15_000:
            return result_str[:15_000] + "\n\n[... output truncated to 15k chars ...]"
        return result_str
    except QuestionError:
        raise
    except Exception as exc:
        logger.exception("Tool {} failed", name)
        return f"[execution_error] {name} failed: {exc}"




_PERMISSION_CHECKER: contextvars.ContextVar[Any] = contextvars.ContextVar("_PERMISSION_CHECKER", default=None)




def set_permission_checker(checker: Any) -> None:
    _PERMISSION_CHECKER.set(checker)




def _get_permission_for_tool(name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
    checker = _PERMISSION_CHECKER.get()
    if checker is not None:
        result = checker(name, arguments)
        if isinstance(result, tuple) and len(result) == 2:
            return (bool(result[0]), str(result[1]))
    reason = _sandbox_deny_reason(name)
    if reason:
        return False, reason
    return True, ""

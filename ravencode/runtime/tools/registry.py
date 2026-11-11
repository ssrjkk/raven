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
from .sandbox_policy import _WEB_BROWSING_TOOLS, _sandbox_deny_reason

_plugin_tools_loaded = False
_plugin_tool_names: set[str] = set()


def _unregistered_plugins_on_disk() -> list[str]:
    """Plugin files on disk that no async entry point registered, by name.

    Loading is async (the worker's pipes belong to the loop that started it), so the surface is
    filled by an entry point calling `register_all_plugins`. Without this check a surface that never
    did would answer "no plugins" silently, which is how the whole subsystem stayed invisible.
    """
    from ravencode.runtime.plugins import get_plugin_registry, plugin_files

    if get_plugin_registry().plugins:
        return []
    try:
        return [p.parent.name for p in plugin_files()]
    except OSError:
        return []


def _ensure_plugin_tools() -> None:
    global _plugin_tools_loaded
    if _plugin_tools_loaded:
        return
    from ravencode.runtime.plugins import get_plugin_registry

    for name, tool in get_plugin_registry().all_tools().items():
        if name in _plugin_tool_names or name not in MODULE_TOOLS:
            MODULE_TOOLS[name] = tool
            _plugin_tool_names.add(name)
        else:
            logger.warning("[plugins] {} is already a built-in tool - the plugin's version is ignored", name)
    unregistered = _unregistered_plugins_on_disk()
    if unregistered:
        logger.warning(
            "[plugins] {} plugin(s) on disk are not on the tool surface because this entry point never "
            "awaited register_all_plugins(): {}",
            len(unregistered),
            ", ".join(unregistered),
        )
    _plugin_tools_loaded = True


def invalidate_plugin_tools() -> None:
    """Forget every plugin-contributed tool so the next call re-reads the registry.

    Removing the names as well as clearing the cache matters: a plugin retracted by a reload would
    otherwise stay callable in this process forever.
    """
    global _plugin_tools_loaded
    for name in _plugin_tool_names:
        MODULE_TOOLS.pop(name, None)
    _plugin_tool_names.clear()
    _plugin_tools_loaded = False
    _build_tool_definitions.cache_clear()


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


def tool_annotations(name: str) -> dict[str, bool]:
    """MCP tool annotations, derived from the same table the execution policy consults."""
    spec = MODULE_TOOLS.get(name) or {}
    return {
        "destructiveHint": bool(spec.get("dangerous", False)),
        "openWorldHint": name in _WEB_BROWSING_TOOLS,
    }


def get_mcp_tool_definitions(plan_mode: bool = False) -> list[dict[str, Any]]:
    """The served tool list in MCP shape, with the hazard hints a client can act on."""
    _ensure_plugin_tools()
    tools: list[dict[str, Any]] = []
    for definition in _build_tool_definitions(plan_mode):
        fn = definition["function"]
        name = str(fn.get("name", ""))
        tools.append(
            {
                "name": name,
                "description": fn.get("description", ""),
                "inputSchema": fn.get("parameters", {"type": "object", "properties": {}}),
                "annotations": tool_annotations(name),
            }
        )
    return tools
def is_dangerous(name: str) -> bool:
    t = MODULE_TOOLS.get(name)
    return bool(t.get("dangerous")) if t else False


class ToolExecutionError(Exception):
    def __init__(self, tool_name: str, detail: str) -> None:
        super().__init__(f"{tool_name} failed: {detail}")
        self.tool_name = tool_name
        self.detail = detail


def _stringify(result: Any) -> str:
    if isinstance(result, list):
        result_str = "\n".join(str(r) for r in result[:200])
    else:
        result_str = str(result)
    if len(result_str) > 15_000:
        return result_str[:15_000] + "\n\n[... output truncated to 15k chars ...]"
    return result_str


async def _invoke(name: str, arguments: dict[str, Any]) -> str:
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
        return _stringify(await tool["handler"](**arguments))
    except QuestionError:
        raise
    except Exception as exc:
        logger.exception("Tool {} failed", name)
        raise ToolExecutionError(name, str(exc)) from exc


@observe_tool(tool_name="execute_tool")
async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    try:
        return await _invoke(name, arguments)
    except ToolExecutionError as exc:
        return f"[execution_error] {exc.tool_name} failed: {exc.detail}"


@observe_tool(tool_name="execute_tool")
async def execute_tool_public(name: str, arguments: dict[str, Any]) -> str:
    # Handler detail must stay out of the return value: these results are written into
    # HTTP/JSON-RPC response bodies, where an exception message is a stack-trace leak.
    try:
        return await _invoke(name, arguments)
    except ToolExecutionError:
        return "[execution_error] tool failed"




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

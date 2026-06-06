from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from raven.core.models import PluginTool


def _type_to_json_schema(tp: Any) -> dict[str, Any]:
    if isinstance(tp, str):
        _type_map = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }
        return {"type": _type_map.get(tp, "string")}
    origin = getattr(tp, "__origin__", None)
    if origin is list or origin is set:
        args = getattr(tp, "__args__", [Any])
        return {"type": "array", "items": _type_to_json_schema(args[0]) if args else {"type": "string"}}
    if origin is dict:
        return {"type": "object"}
    if tp is str or tp is type(None) or tp is Any:
        return {"type": "string"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is bool:
        return {"type": "boolean"}
    return {"type": "string"}


def func_to_tool(func: Callable[..., Any]) -> PluginTool:
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ""
    desc_lines = doc.strip().split("\n") if doc.strip() else []
    first = desc_lines[0] if desc_lines else func.__name__
    description = re.split(r"\s*(?:Args|Returns|Example):", first, maxsplit=1)[0].strip() or first

    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    for name, param in sig.parameters.items():
        if name == "self" or name == "cls":
            continue
        tp = param.annotation if param.annotation is not inspect.Parameter.empty else str
        schema = _type_to_json_schema(tp)
        param_doc = ""
        for line in desc_lines:
            match = re.match(rf"\s*{re.escape(name)}\s*\(?\s*:?\s*(.*)", line, re.IGNORECASE)
            if match:
                param_doc = match.group(1).strip()
                break
        if param_doc:
            schema["description"] = param_doc
        parameters["properties"][name] = schema
        if param.default is inspect.Parameter.empty:
            parameters["required"].append(name)

    return PluginTool(
        name=func.__name__,
        description=description,
        parameters=parameters,
        handler=func,
    )


def _tool_to_openai_format(tool: PluginTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


class PluginLoader:
    def __init__(self):
        self._tools: dict[str, PluginTool] = {}
        self._skills: dict[str, str] = {}

    def load_from_dir(self, path: Path) -> list[PluginTool]:
        if not path.exists():
            logger.warning("Plugin directory not found: {}", path)
            return []
        plugin_file = path / "plugin.py"
        if not plugin_file.exists():
            logger.warning("No plugin.py in {}", path)
            return []

        spec = importlib.util.spec_from_file_location(path.name, plugin_file)
        if not spec or not spec.loader:
            logger.error("Failed to load plugin: {}", plugin_file)
            return []

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        tools = []
        for name, obj in inspect.getmembers(mod, inspect.iscoroutinefunction):
            if name.startswith("_"):
                continue
            tool = func_to_tool(obj)
            self._tools[tool.name] = tool
            tools.append(tool)
            logger.debug("Loaded tool: {}", tool.name)

        skill_file = path / "SKILL.md"
        if skill_file.exists():
            skill_content = skill_file.read_text()
            self._skills[path.name] = skill_content
            logger.debug("Loaded skill: {}", path.name)

        return tools

    def load_skill_md(self, path: Path) -> str:
        if path.exists() and path.suffix == ".md":
            content = path.read_text()
            self._skills[path.stem] = content
            return content
        return ""

    @property
    def tools(self) -> list[PluginTool]:
        return list(self._tools.values())

    @property
    def skills(self) -> list[str]:
        return list(self._skills.values())

    def get_tool(self, name: str) -> PluginTool | None:
        return self._tools.get(name)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [_tool_to_openai_format(t) for t in self._tools.values()]

    def clear(self):
        self._tools.clear()
        self._skills.clear()

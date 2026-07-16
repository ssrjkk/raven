from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.models import PluginTool

# ---------------------------------------------------------------------------
# Worker pool for untrusted plugins
# ---------------------------------------------------------------------------

_WORKER_POOL: dict[str, WorkerProcess] = {}


class WorkerProcess:
    def __init__(self, plugin_path: Path) -> None:
        self._plugin_path = plugin_path
        self._process: asyncio.subprocess.Process | None = None

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        worker_script = Path(__file__).resolve().parent / "plugin_worker.py"
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, str(worker_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def send_command(self, cmd: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        await self._ensure_started()
        proc = self._process
        assert proc is not None
        stdin = proc.stdin
        stdout = proc.stdout
        assert stdin is not None
        assert stdout is not None

        raw = json.dumps(cmd) + "\n"
        stdin.write(raw.encode("utf-8"))
        await stdin.drain()

        while True:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
            if not line:
                raise RuntimeError("worker closed connection")
            msg = json.loads(line.decode("utf-8"))
            if msg.get("type") == "capability":
                result = await _handle_capability_from_worker(msg)
                resp: dict[str, Any] = {"type": "capability_response", "id": msg.get("id", ""), "result": result}
                stdin.write((json.dumps(resp) + "\n").encode("utf-8"))
                await stdin.drain()
            else:
                result_msg: dict[str, Any] = msg
                return result_msg

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()

    @property
    def plugin_path(self) -> Path:
        return self._plugin_path


async def _handle_capability_from_worker(msg: dict[str, Any]) -> str:
    from raven.core.plugin_context import handle_capability
    plugin = msg.get("plugin", "unknown")
    capability = msg.get("capability", "")
    args = msg.get("args", {})
    result = await handle_capability(plugin, capability, args)
    return result if result is not None else "[denied] capability not available"


async def register_untrusted_plugin(plugin_dir: Path, register_timeout: float = 2.0) -> dict[str, Any] | None:
    plugin_file = plugin_dir / "plugin.py"
    if not plugin_file.exists():
        logger.warning("No plugin.py in {}", plugin_dir)
        return None
    worker = WorkerProcess(plugin_file)
    try:
        resp = await worker.send_command({
            "type": "register",
            "path": str(plugin_file),
            "register_timeout": register_timeout,
        }, timeout=register_timeout + 2.0)
        if resp.get("type") == "register_ok":
            key = str(plugin_file)
            _WORKER_POOL[key] = worker
            logger.info("Untrusted plugin registered: {}", plugin_dir.name)
            return {
                "name": plugin_dir.name,
                "tools": resp.get("tools", []),
            }
        else:
            logger.error("Plugin registration failed: {} — {}", plugin_dir.name, resp.get("error"))
            await worker.stop()
            return None
    except Exception as e:
        logger.error("Plugin registration error for {}: {}", plugin_dir.name, e)
        await worker.stop()
        return None


async def call_untrusted_tool(plugin_file: str, tool_name: str, args: dict[str, Any], timeout: float = 30.0) -> str:
    worker = _WORKER_POOL.get(plugin_file)
    if not worker:
        raise RuntimeError(f"Plugin not registered: {plugin_file}")
    resp = await worker.send_command({
        "type": "call_tool",
        "path": plugin_file,
        "tool": tool_name,
        "args": args,
        "tool_timeout": timeout,
    }, timeout=timeout + 10.0)
    if resp.get("type") == "result":
        result: Any = resp["result"]
        return str(result) if result is not None else ""
    error = resp.get("error", "unknown error")
    raise RuntimeError(error)


async def stop_untrusted_plugins() -> None:
    for worker in _WORKER_POOL.values():
        await worker.stop()
    _WORKER_POOL.clear()


# ---------------------------------------------------------------------------
# Trusted plugin loading (existing importlib)
# ---------------------------------------------------------------------------

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

    async def load_untrusted_from_dir(self, path: Path) -> list[dict[str, Any]]:
        result = await register_untrusted_plugin(path)
        if result is None:
            return []
        tools_raw: list[dict[str, Any]] = result.get("tools", [])
        plugin_file = str(path / "plugin.py")
        for t in tools_raw:
            t["handler"] = _make_untrusted_handler(plugin_file, t["name"])
        return tools_raw

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


def _make_untrusted_handler(plugin_file: str, tool_name: str) -> Callable[..., Any]:
    async def handler(**kwargs: Any) -> str:
        return await call_untrusted_tool(plugin_file, tool_name, kwargs)
    return handler

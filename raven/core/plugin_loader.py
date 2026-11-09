from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import inspect
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from loguru import logger

from raven.core.models import PluginTool
from raven.plugins.manifest import PluginManifest

try:
    _RAVEN_VERSION = importlib.metadata.version("raven-agent")
except importlib.metadata.PackageNotFoundError:
    _RAVEN_VERSION = "0.0.0"

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
            sys.executable,
            str(worker_script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def send_command(self, cmd: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        await self._ensure_started()
        proc = self._process
        if proc is None:
            raise RuntimeError("Plugin subprocess not started")
        stdin = proc.stdin
        stdout = proc.stdout
        if stdin is None or stdout is None:
            raise RuntimeError("Plugin subprocess pipes not available")

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
        resp = await worker.send_command(
            {
                "type": "register",
                "path": str(plugin_file),
                "register_timeout": register_timeout,
            },
            timeout=register_timeout + 2.0,
        )
        if resp.get("type") == "register_ok":
            key = str(plugin_file)
            _WORKER_POOL[key] = worker
            logger.info("Untrusted plugin registered: {}", plugin_dir.name)
            return {
                "name": plugin_dir.name,
                "tools": resp.get("tools", []),
            }
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
        msg = f"Plugin not registered: {plugin_file}"
        raise RuntimeError(msg)
    resp = await worker.send_command(
        {
            "type": "call_tool",
            "path": plugin_file,
            "tool": tool_name,
            "args": args,
            "tool_timeout": timeout,
        },
        timeout=timeout + 10.0,
    )
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


def _published_by_this_plugin(mod: ModuleType, attr_name: str, func: Callable[..., Any]) -> bool:
    """True only for a coroutine defined by this plugin.py, under its own name.

    ``inspect.getmembers`` also returns coroutines the module imported, and plugin modules import
    helpers freely: api and browser both import ``safe_fetch_async`` from the SSRF layer, memory
    imports ``run_python`` from the code plugin. Every one of those became a callable tool on the
    model surface, under a name no operator had written down and no policy rule addressed.
    """
    return getattr(func, "__module__", None) == mod.__name__ and attr_name == func.__name__


_PARAM_DOC = re.compile(r"^(?P<name>\w+)\s*(?:\([^)]*\))?\s*:\s*(?P<text>.*)$")
_SECTION_BREAK = re.compile(r"^[A-Za-z][A-Za-z ]*:$")


def _param_docs(lines: list[str], names: list[str]) -> dict[str, str]:
    """Collect the 'name: text' lines of a docstring, joining the wrapped continuation of each.

    Reading only the line that starts with the parameter name cut every description that a plugin
    author wrapped onto a second line down to its first clause, and matched any sentence that merely
    began with that word.
    """
    wanted = set(names)
    docs: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        text = line.strip()
        if not text or _SECTION_BREAK.match(text):
            current = None
            continue
        match = _PARAM_DOC.match(text)
        if match and match.group("name") in wanted:
            current = match.group("name")
            docs.setdefault(current, []).append(match.group("text").strip())
            continue
        if current is not None:
            docs[current].append(text)
    return {name: " ".join(part for part in parts if part) for name, parts in docs.items()}


def func_to_tool(func: Callable[..., Any]) -> PluginTool:
    sig = inspect.signature(func)
    doc = inspect.getdoc(func) or ""
    desc_lines = doc.strip().split("\n") if doc.strip() else []
    first = desc_lines[0] if desc_lines else func.__name__
    description = re.split(r"\s*(?:Args|Returns|Example):", first, maxsplit=1)[0].strip() or first
    arg_names = [name for name in sig.parameters if name not in ("self", "cls")]
    param_docs = _param_docs(desc_lines[1:], arg_names)

    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
    for name, param in sig.parameters.items():
        if name == "self" or name == "cls":
            continue
        tp = param.annotation if param.annotation is not inspect.Parameter.empty else str
        schema = _type_to_json_schema(tp)
        param_doc = param_docs.get(name, "")
        if param_doc:
            schema["description"] = param_doc
        parameters["properties"][name] = schema
        # a *args/**kwargs slot can never be supplied by name in a JSON tool call, so it is never required
        if param.default is inspect.Parameter.empty and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
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
        self._manifests: dict[str, PluginManifest] = {}

    def _load_manifest(self, path: Path) -> PluginManifest | None:
        manifest_path = path / "manifest.json"
        if manifest_path.exists():
            manifest = PluginManifest.from_file(manifest_path)
            if manifest is None:
                logger.error("Plugin {} rejected: invalid manifest.json", path.name)
                return None
        else:
            manifest = PluginManifest(name=path.name)
        error = manifest.validate(_RAVEN_VERSION)
        if error:
            logger.error("Plugin {} rejected: {}", path.name, error)
            return None
        self._manifests[path.name] = manifest
        logger.debug(
            "Plugin {} v{} loaded (permissions: {}, requires: {})",
            manifest.name or path.name,
            manifest.version,
            manifest.permissions,
            manifest.requires,
        )
        return manifest

    def load_from_dir(self, path: Path) -> list[PluginTool]:
        if not path.exists():
            logger.warning("Plugin directory not found: {}", path)
            return []
        plugin_file = path / "plugin.py"
        if not plugin_file.exists():
            logger.warning("No plugin.py in {}", path)
            return []
        manifest = self._load_manifest(path)
        if manifest is None:
            return []

        spec = importlib.util.spec_from_file_location(path.name, plugin_file)
        if not spec or not spec.loader:
            logger.error("Failed to load plugin: {}", plugin_file)
            return []

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        tools = []
        namespace = path.name
        for name, obj in inspect.getmembers(mod, inspect.iscoroutinefunction):
            if name.startswith("_"):
                continue
            if not _published_by_this_plugin(mod, name, obj):
                logger.debug("Skipped {} in plugin {}: imported, not defined here", name, path.name)
                continue
            tool = func_to_tool(obj)
            if tool.description == obj.__name__:
                logger.warning(
                    "Plugin tool {}.{} has no docstring: the model sees only the bare name", namespace, tool.name
                )
            tool.name = f"{namespace}.{tool.name}"
            self._tools[tool.name] = tool
            tools.append(tool)
            logger.debug("Loaded tool: {}", tool.name)

        skill_file = path / "SKILL.md"
        if skill_file.exists():
            skill_content = skill_file.read_text(encoding="utf-8")
            self._skills[path.name] = skill_content
            logger.debug("Loaded skill: {}", path.name)

        return tools

    async def load_untrusted_from_dir(self, path: Path) -> list[dict[str, Any]]:
        manifest = self._load_manifest(path)
        if manifest is None:
            return []
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
            content = path.read_text(encoding="utf-8")
            self._skills[path.stem] = content
            return content
        return ""

    @property
    def tools(self) -> list[PluginTool]:
        return list(self._tools.values())

    @property
    def skills(self) -> list[str]:
        return list(self._skills.values())

    @property
    def manifests(self) -> dict[str, PluginManifest]:
        return dict(self._manifests)

    def get_manifest(self, plugin_name: str) -> PluginManifest | None:
        return self._manifests.get(plugin_name)

    def get_tool(self, name: str) -> PluginTool | None:
        return self._tools.get(name)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [_tool_to_openai_format(t) for t in self._tools.values()]

    def clear(self):
        self._tools.clear()
        self._skills.clear()
        self._manifests.clear()


def _make_untrusted_handler(plugin_file: str, tool_name: str) -> Callable[..., Any]:
    async def handler(**kwargs: Any) -> str:
        return await call_untrusted_tool(plugin_file, tool_name, kwargs)

    return handler

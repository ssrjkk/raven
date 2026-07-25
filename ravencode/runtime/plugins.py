from __future__ import annotations

import asyncio
import contextlib
import importlib.util
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

ToolHandler = Callable[..., Awaitable[str]]


class Plugin:
    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        tools: dict[str, dict[str, Any]] | None = None,
        on_load: Callable[[], None] | None = None,
        on_unload: Callable[[], None] | None = None,
        _source_path: str | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.tools: dict[str, dict[str, Any]] = tools or {}
        self._on_load = on_load
        self._on_unload = on_unload
        self._source_path = _source_path

    def load(self) -> None:
        if self._on_load:
            self._on_load()
        logger.info("Plugin loaded: {} v{}", self.name, self.version)

    def unload(self) -> None:
        if self._on_unload:
            self._on_unload()
        logger.info("Plugin unloaded: {}", self.name)


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._tool_map: dict[str, str] = {}
        self._file_mtimes: dict[str, float] = {}
        self._watch_task: asyncio.Task[None] | None = None
        self._on_reload: Callable[[str], None] | None = None

    def register(self, plugin: Plugin) -> None:
        if plugin.name in self._plugins:
            logger.warning("Plugin already registered: {}", plugin.name)
            return
        plugin.load()
        self._plugins[plugin.name] = plugin
        for tool_name in plugin.tools:
            self._tool_map[tool_name] = plugin.name
        if plugin._source_path:
            self._track_file(plugin._source_path)
        logger.info("Plugin registered: {} ({} tools)", plugin.name, len(plugin.tools))

    def unregister(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin:
            for tool_name in list(plugin.tools):
                self._tool_map.pop(tool_name, None)
            plugin.unload()

    def get_plugin(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def get_tool_owner(self, tool_name: str) -> str | None:
        return self._tool_map.get(tool_name)

    def all_tools(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for plugin in self._plugins.values():
            result.update(plugin.tools)
        return result

    @property
    def plugins(self) -> dict[str, Plugin]:
        return dict(self._plugins)

    def set_on_reload(self, callback: Callable[[str], None] | None) -> None:
        self._on_reload = callback

    def _track_file(self, path: str) -> None:
        try:
            p = Path(path)
            if p.is_file():
                self._file_mtimes[path] = p.stat().st_mtime
        except OSError:
            pass

    async def watch(self, interval: float = 3.0) -> None:
        if self._watch_task is not None:
            return
        async def _poll() -> None:
            while True:
                await asyncio.sleep(interval)
                await self._check_reload()
        self._watch_task = asyncio.create_task(_poll())
        logger.debug("[plugins] watch started (interval={}s)", interval)

    async def stop_watch(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch_task
            self._watch_task = None
        logger.debug("[plugins] watch stopped")

    async def _check_reload(self) -> None:
        changed: list[str] = []
        for path, old_mtime in list(self._file_mtimes.items()):
            try:
                p = Path(path)
                if p.is_file() and p.stat().st_mtime != old_mtime:
                    changed.append(path)
            except OSError:
                continue
        for path in changed:
            plugin_name = self._find_plugin_by_source(path)
            if plugin_name:
                logger.info("[plugins] detected change in {}, reloading...", path)
                await self._reload_plugin(plugin_name)

    def _find_plugin_by_source(self, source_path: str) -> str | None:
        for name, plugin in self._plugins.items():
            if plugin._source_path == source_path:
                return name
        return None

    async def _reload_plugin(self, name: str) -> None:
        old_plugin = self._plugins.get(name)
        if not old_plugin or not old_plugin._source_path:
            return
        source = Path(old_plugin._source_path)
        if not source.is_file():
            return
        self.unregister(name)
        try:
            new_plugin = _load_plugin_from_file(source)
            if new_plugin:
                new_plugin._source_path = str(source)
                self.register(new_plugin)
                if self._on_reload:
                    self._on_reload(name)
                logger.info("[plugins] reloaded: {}", name)
        except Exception as exc:
            logger.error("[plugins] reload failed for {}: {}", name, exc)


_plugin_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


def discover_plugins(plugins_dir: str | Path | None = None) -> list[Plugin]:
    """Scan directories for plugin.py files and load them (untrusted → subprocess worker).

    Search order:
    1. Explicit plugins_dir parameter
    2. `plugins/` at project root
    3. `~/.config/raven/plugins/`
    """
    candidates = []
    if plugins_dir:
        candidates.append(Path(plugins_dir).expanduser().resolve())
    candidates.append(Path.cwd() / "plugins")
    candidates.append(Path.home() / ".config" / "raven" / "plugins")

    found: list[Plugin] = []
    seen: set[str] = set()

    for base in candidates:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            plugin_file = entry / "plugin.py"
            if not plugin_file.is_file():
                continue
            if entry.name in seen:
                continue
            try:
                plugin = _load_untrusted_plugin_via_worker(plugin_file)
                if plugin:
                    plugin._source_path = str(plugin_file)
                    found.append(plugin)
                    seen.add(entry.name)
            except Exception as exc:
                logger.error("Failed to load plugin from {}: {}", plugin_file, exc)

    logger.info("Discovered {} plugin(s)", len(found))
    return found


def _load_untrusted_plugin_via_worker(path: Path) -> Plugin | None:
    from raven.core.plugin_loader import call_untrusted_tool, register_untrusted_plugin

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(register_untrusted_plugin(path))
    else:
        result = loop.run_until_complete(register_untrusted_plugin(path))
    if result is None:
        return None

    name = result["name"]
    tools_meta = result.get("tools", [])
    plugin_file = str(path)

    def _make_handler(tool_name: str) -> Callable[..., Awaitable[str]]:
        async def _handler(**kwargs: Any) -> str:
            return await call_untrusted_tool(plugin_file, tool_name, kwargs)

        return _handler

    tools: dict[str, dict[str, Any]] = {}
    for t in tools_meta:
        tname = t["name"]
        tools[tname] = {
            "name": tname,
            "dangerous": t.get("dangerous", False),
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {}),
            "handler": _make_handler(tname),
        }

    return Plugin(name=name, tools=tools)


def _load_plugin_from_file(path: Path) -> Plugin | None:
    try:
        spec = importlib.util.spec_from_file_location(f"plugin_{path.parent.name}", str(path))
        if not spec or not spec.loader:
            logger.warning("Cannot load plugin spec: {}", path)
            return None

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        if not hasattr(mod, "register"):
            logger.warning("Plugin {} has no register() function", path.parent.name)
            return None

        plugin = mod.register()
        if not isinstance(plugin, Plugin):
            logger.warning("Plugin {} register() did not return a Plugin instance", path.parent.name)
            return None

        plugin._source_path = str(path)
        return plugin
    except SyntaxError as exc:
        logger.warning("Plugin {} has syntax error: {}", path.parent.name, exc)
        return None
    except FileNotFoundError:
        logger.warning("Plugin file not found: {}", path)
        return None
    except Exception as exc:
        logger.warning("Failed to load plugin {}: {}", path.parent.name, exc)
        return None


def register_all_plugins(plugins_dir: str | Path | None = None, watch: bool = True) -> int:
    registry = get_plugin_registry()
    plugins = discover_plugins(plugins_dir)
    for p in plugins:
        registry.register(p)
    if watch:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(registry.watch(interval=3.0))  # noqa: RUF006
        except RuntimeError:
            pass
    return len(plugins)


def register_internal_plugins(internal_plugins_dir: str | Path | None = None) -> int:
    """Bridge: discover internal Raven plugins (raven/plugins/) and register them
    as external Plugin objects. Returns the number of plugins registered."""
    from raven.core.plugin_loader import PluginLoader

    loader = PluginLoader()
    if internal_plugins_dir:
        base = Path(internal_plugins_dir)
    else:
        base = Path(__file__).resolve().parent.parent.parent / "raven" / "plugins"

    count = 0
    registry = get_plugin_registry()
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        plugin_file = entry / "plugin.py"
        if not plugin_file.is_file():
            continue
        try:
            tools_from_dir = loader.load_from_dir(entry)
            if not tools_from_dir:
                continue
            name = entry.name
            tools: dict[str, dict[str, Any]] = {}
            for t in tools_from_dir:
                tools[t.name] = {
                    "name": t.name,
                    "dangerous": False,
                    "description": t.description,
                    "parameters": t.parameters,
                    "handler": t.handler,
                }
            plugin = Plugin(name=name, tools=tools)
            registry.register(plugin)
            count += 1
            logger.info("Registered internal plugin via bridge: {} ({} tool(s))", name, len(tools))
        except Exception as exc:
            logger.warning("Failed to bridge internal plugin {}: {}", entry.name, exc)
    logger.info("Bridged {} internal plugin(s)", count)
    return count

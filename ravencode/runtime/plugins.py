from __future__ import annotations

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
    ) -> None:
        self.name = name
        self.version = version
        self.tools: dict[str, dict[str, Any]] = tools or {}
        self._on_load = on_load
        self._on_unload = on_unload

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

    def register(self, plugin: Plugin) -> None:
        if plugin.name in self._plugins:
            logger.warning("Plugin already registered: {}", plugin.name)
            return
        plugin.load()
        self._plugins[plugin.name] = plugin
        for tool_name in plugin.tools:
            self._tool_map[tool_name] = plugin.name
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


_plugin_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


def discover_plugins(plugins_dir: str | Path | None = None) -> list[Plugin]:
    """Scan directories for plugin.py files and load them.

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
                plugin = _load_plugin_from_file(plugin_file)
                if plugin:
                    found.append(plugin)
                    seen.add(entry.name)
            except Exception as exc:
                logger.error("Failed to load plugin from {}: {}", plugin_file, exc)

    logger.info("Discovered {} plugin(s)", len(found))
    return found


def _load_plugin_from_file(path: Path) -> Plugin | None:
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

    return plugin


def register_all_plugins(plugins_dir: str | Path | None = None) -> int:
    """Discover and register all plugins, returning the count."""
    registry = get_plugin_registry()
    plugins = discover_plugins(plugins_dir)
    for p in plugins:
        registry.register(p)
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

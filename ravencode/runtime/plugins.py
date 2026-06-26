from __future__ import annotations

from collections.abc import Awaitable, Callable
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

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
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
        _invalidate_tool_surface()
        logger.info("Plugin registered: {} ({} tools)", plugin.name, len(plugin.tools))

    def unregister(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin:
            for tool_name in list(plugin.tools):
                self._tool_map.pop(tool_name, None)
            plugin.unload()
            _invalidate_tool_surface()

    def get_plugin(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def plugin_by_source(self, source_path: str) -> Plugin | None:
        """The plugin loaded from this file, if any — a reload reuses the worker rather than forking one."""
        for plugin in self._plugins.values():
            if plugin._source_path == source_path:
                return plugin
        return None

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

    def _track_file(self, path: str) -> None:
        try:
            p = Path(path)
            if p.is_file():
                self._file_mtimes[path] = p.stat().st_mtime
        except OSError:
            pass

    async def watch(self, interval: float = 3.0) -> None:
        if self._watch_task is not None and not self._watch_task.done():
            if self._watch_task.get_loop() is asyncio.get_running_loop():
                return
            # A task in another loop cannot be awaited or cancelled from here, and it will never run
            # again if that loop has closed. Drop it and poll from the loop that is asking.
            logger.debug("[plugins] reload watcher belonged to another loop, replacing it")
            self._watch_task = None

        async def _poll() -> None:
            while True:
                await asyncio.sleep(interval)
                await self._check_reload()

        self._watch_task = asyncio.create_task(_poll())
        logger.debug("[plugins] watch started (interval={}s)", interval)

    async def stop_watch(self) -> None:
        task, self._watch_task = self._watch_task, None
        if task is None:
            return
        if task.get_loop() is not asyncio.get_running_loop():
            logger.debug("[plugins] reload watcher belongs to another loop, reference dropped")
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
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
            new_plugin = await _load_untrusted_plugin(source.parent)
            if new_plugin:
                self.register(new_plugin)
                logger.info("[plugins] reloaded: {}", name)
        except Exception as exc:
            logger.error("[plugins] reload failed for {}: {}", name, exc)


def _invalidate_tool_surface() -> None:
    """Drop the cached tool definitions so the next model call sees the registry as it is now.

    Called from register/unregister rather than from the loading entry points: a plugin retracted by a
    reload would otherwise stay on the surface and the model would keep calling a tool the worker no
    longer has.
    """
    from ravencode.runtime.tools.registry import invalidate_plugin_tools

    invalidate_plugin_tools()


async def shutdown_plugins() -> None:
    """Stop the reload watcher and every sandbox interpreter this process started.

    Each user plugin runs in its own interpreter with an open stdin pipe; a server that exits without
    this leaves those children behind, and the operator sees orphan `python -P plugin_worker.py`
    processes after the app is gone.
    """
    from raven.core.plugin_loader import stop_untrusted_plugins

    await get_plugin_registry().stop_watch()
    await stop_untrusted_plugins()


@contextlib.asynccontextmanager
async def running_plugin_tools(*, watch: bool = False) -> AsyncIterator[None]:
    """Hold the user-plugin tool surface open for one async flow.

    Registration and the tool calls it enables must share a loop: a sandbox worker's pipes belong to the
    loop that started it, so a flow that registered in one `asyncio.run` and called tools in the next
    would reach a worker whose loop had already closed. Servers whose loop outlives a request can also
    call `ensure_plugin_tools` and `shutdown_plugins` at their own start and stop.
    """
    await ensure_plugin_tools(watch=watch)
    try:
        yield
    finally:
        await shutdown_plugins()


_plugin_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


def plugin_directories(plugins_dir: str | Path | None = None) -> list[Path]:
    """The directories user plugins are read from, in precedence order.

    The artifact resolver owns this list — env (`PLUGINS_DIR`/`RAVEN_PLUGINS_DIR`), `raven.json`
    `paths.plugins`, `.raven.local/plugins`, `.raven/plugins`, `~/.config/raven/plugins` and the
    legacy `plugins/` next to the checkout. Naming two of them here instead would have given the
    same operator setting two answers, and the resolver already filters to directories that exist.
    """
    if plugins_dir is not None:
        return [Path(plugins_dir).expanduser().resolve()]
    from raven.core.artifacts.paths import ArtifactPaths

    return ArtifactPaths.resolve().plugins


def _plugin_files(directories: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for base in directories:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            plugin_file = entry / "plugin.py"
            if not plugin_file.is_file() or entry.name in seen:
                continue
            seen.add(entry.name)
            found.append(plugin_file)
    return found


def plugin_files(plugins_dir: str | Path | None = None) -> list[Path]:
    """Every user plugin source this process can load, in the order the resolver prefers.

    Read-only, so a surface that reports the state of plugins (doctor) does not have to start a sandbox
    interpreter just to count what is on disk.
    """
    return _plugin_files(plugin_directories(plugins_dir))


async def discover_plugins(plugins_dir: str | Path | None = None) -> list[Plugin]:
    """Load every user plugin on disk through the untrusted worker.

    Async because the worker is a subprocess whose pipes belong to the loop that started it: a sync
    wrapper had to own the loop, and a loop closed after registration left the pooled worker
    unreachable for the one call that mattered — running a tool.
    """
    registry = get_plugin_registry()
    from raven.core.plugin_loader import worker_state

    found: list[Plugin] = []
    for plugin_file in plugin_files(plugins_dir):
        source = str(plugin_file)
        try:
            if (live := registry.plugin_by_source(source)) is not None and worker_state(source) != "gone":
                found.append(live)
                continue
            plugin = await _load_untrusted_plugin(plugin_file.parent)
        except Exception as exc:
            logger.error("Failed to load plugin from {}: {}", plugin_file, exc)
            continue
        if plugin:
            found.append(plugin)

    logger.info("Discovered {} plugin(s)", len(found))
    return found


async def _load_untrusted_plugin(plugin_dir: Path) -> Plugin | None:
    """Register one plugin directory and wrap its tools for this process's loop.

    Tools are namespaced by the plugin directory (`weather.get_forecast`), which is what the plugin
    guide documents for the bundled stack and what keeps two plugins from publishing one name. It
    also gives every tool a policy-addressable identity: a bare `http_post` from a plugin would have
    been a different string from the `api.http_post` the ruleset denies.
    """
    from raven.core.plugin_loader import call_untrusted_tool, register_untrusted_plugin

    result = await register_untrusted_plugin(plugin_dir)
    if result is None:
        return None

    plugin_file = str(plugin_dir / "plugin.py")
    namespace = plugin_dir.name

    def _make_handler(worker_tool: str) -> Callable[..., Awaitable[str]]:
        async def _handler(**kwargs: Any) -> str:
            return await call_untrusted_tool(plugin_file, worker_tool, kwargs)

        return _handler

    tools: dict[str, dict[str, Any]] = {}
    for t in result.get("tools", []):
        tool_name = f"{namespace}.{t['name']}"
        tools[tool_name] = {
            "name": tool_name,
            "dangerous": t.get("dangerous", False),
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {}),
            "handler": _make_handler(t["name"]),
        }

    return Plugin(name=result["name"], tools=tools, _source_path=plugin_file)


async def register_all_plugins(plugins_dir: str | Path | None = None, watch: bool = False) -> int:
    """Load every user plugin into the registry the tool surface drains.

    Call this from an async entry point; `watch` then keeps it hot-reloading on that same loop. A plugin
    whose worker was started by a loop that has since closed is dropped and re-registered here, so a
    second surface in one process gets a worker it can actually talk to instead of a tool that times out.
    """
    from raven.core.plugin_loader import worker_state

    registry = get_plugin_registry()
    for name, plugin in list(registry.plugins.items()):
        if plugin._source_path and worker_state(plugin._source_path) == "gone":
            logger.debug("[plugins] {} has no worker on this loop, re-registering", name)
            registry.unregister(name)
    plugins = await discover_plugins(plugins_dir)
    for p in plugins:
        if registry.get_plugin(p.name) is not p:
            registry.register(p)
    if watch:
        await registry.watch()
    return len(plugins)


_plugins_attempted = False
_plugins_loop: asyncio.AbstractEventLoop | None = None


async def ensure_plugin_tools(*, watch: bool = False, force: bool = False) -> int:
    """Register user plugins once per loop, from an async entry point.

    Every surface that builds a tool list reaches this beside `ensure_mcp_tools`: the loading is
    async, so it cannot happen inside the synchronous first call of `get_tool_definitions`, and a
    surface that simply did not call it would report a plugin-free agent. "Once" is per event loop,
    not per process — a worker started by a loop that has ended answers nothing on the next one.
    """
    global _plugins_attempted, _plugins_loop
    loop = asyncio.get_running_loop()
    if _plugins_attempted and _plugins_loop is loop and not force:
        return 0
    _plugins_attempted = True
    _plugins_loop = loop
    try:
        return await register_all_plugins(watch=watch)
    except Exception as exc:
        logger.warning("Plugin discovery unavailable: {}", exc)
        return 0

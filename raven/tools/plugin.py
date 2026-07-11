from __future__ import annotations

from loguru import logger

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.unique.plugin_marketplace import PluginCatalog, PluginManager

_catalog: PluginCatalog | None = None
_manager: PluginManager | None = None


def _get_manager() -> PluginManager:
    global _manager
    if _manager is None:
        _catalog_local = PluginCatalog()
        _manager = PluginManager(catalog=_catalog_local)
    return _manager


def _get_catalog() -> PluginCatalog:
    global _catalog
    if _catalog is None:
        _catalog = PluginCatalog()
    return _catalog


async def plugin_list_installed() -> str:
    manager = _get_manager()
    installed = manager.list_installed()
    if not installed:
        return "[info] No plugins installed."
    lines = [f"Installed plugins ({len(installed)}):"]
    for p in installed:
        lines.append(
            f"  - {p.metadata.name} v{p.metadata.version} "
            f"[{p.metadata.category.value}] "
            f"status={p.status.value}"
        )
    return "\n".join(lines)


async def plugin_search(query: str = "") -> str:
    if not query:
        return "[info] Provide a search query."
    manager = _get_manager()
    results = manager.search_plugins(query)
    if not results:
        return f"[info] No plugins found for '{query}'."
    lines = [f"Plugin search results for '{query}' ({len(results)}):"]
    for p in results:
        lines.append(f"  - {p.name} v{p.version} [{p.category.value}] {p.description[:80]}")
    return "\n".join(lines)


async def plugin_install(url_or_path: str, source: str = "remote") -> str:
    manager = _get_manager()
    try:
        result = await manager.install_plugin(url_or_path, source=source)
        return f"Installed '{result.metadata.name}' v{result.metadata.version} ({result.status.value})"
    except Exception as e:
        logger.error("Plugin install failed: {}", e)
        return f"[error] Install failed: {e}"


async def plugin_uninstall(name: str) -> str:
    manager = _get_manager()
    try:
        ok = await manager.uninstall_plugin(name)
        if ok:
            return f"Uninstalled '{name}'."
        return f"[error] Plugin '{name}' not found."
    except Exception as e:
        logger.error("Plugin uninstall failed: {}", e)
        return f"[error] Uninstall failed: {e}"


async def plugin_info(name: str) -> str:
    manager = _get_manager()
    info = manager.get_plugin_info(name)
    if info is None:
        return f"[info] Plugin '{name}' not found."
    status = manager.get_installation_status(name)
    return (
        f"Plugin: {info.name}\n"
        f"- Version: {info.version}\n"
        f"- Author: {info.author}\n"
        f"- Category: {info.category.value}\n"
        f"- Status: {status.value}\n"
        f"- Description: {info.description}\n"
        f"- Tags: {', '.join(info.tags) if info.tags else 'none'}"
    )


async def plugin_catalog_top(limit: int = 10) -> str:
    catalog = _get_catalog()
    await catalog.sync()
    top = catalog.get_top_rated(limit)
    if not top:
        return "[info] No rated plugins in catalog."
    lines = [f"Top rated plugins ({len(top)}):"]
    for p, rating in top:
        lines.append(f"  - {p.name} v{p.version} [{p.category.value}] ★ {rating:.1f}")
    return "\n".join(lines)


async def plugin_catalog_browse(category: str = "") -> str:
    catalog = _get_catalog()
    await catalog.sync()
    plugins = list(catalog._plugins.values())
    if category:
        plugins = [p for p in plugins if p.category.value == category]
    if not plugins:
        return f"[info] No plugins in catalog{' for category ' + category if category else ''}."
    lines = [f"Catalog plugins ({len(plugins)}):"]
    for p in plugins:
        lines.append(f"  - {p.name} v{p.version} [{p.category.value}] {p.description[:70]}")
    return "\n".join(lines)


def register_plugin_tools(registry: ToolRegistry) -> None:
    registry.register(ToolSpec(
        name="plugin_list_installed",
        description="List all installed plugins",
        parameters={},
        handler=plugin_list_installed,
        category="plugins",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="plugin_search",
        description="Search plugins in catalog and installed list",
        parameters={
            "query": {"type": "string", "description": "Search query", "required": True},
        },
        handler=plugin_search,
        category="plugins",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="plugin_install",
        description="Install a plugin from URL, path, or catalog ID",
        parameters={
            "url_or_path": {"type": "string", "description": "Git URL, path, or catalog ID", "required": True},
            "source": {"type": "string", "description": "Source type: remote or local", "required": False},
        },
        handler=plugin_install,
        category="plugins",
        timeout=120,
    ))
    registry.register(ToolSpec(
        name="plugin_uninstall",
        description="Uninstall a plugin by name",
        parameters={
            "name": {"type": "string", "description": "Plugin name to uninstall", "required": True},
        },
        handler=plugin_uninstall,
        category="plugins",
        timeout=30,
    ))
    registry.register(ToolSpec(
        name="plugin_info",
        description="Get detailed information about a plugin",
        parameters={
            "name": {"type": "string", "description": "Plugin name", "required": True},
        },
        handler=plugin_info,
        category="plugins",
        timeout=10,
    ))
    registry.register(ToolSpec(
        name="plugin_catalog_top",
        description="List top-rated plugins from the catalog",
        parameters={
            "limit": {"type": "integer", "description": "Number of results (default 10)", "required": False},
        },
        handler=plugin_catalog_top,
        category="plugins",
        timeout=30,
    ))
    registry.register(ToolSpec(
        name="plugin_catalog_browse",
        description="Browse all plugins in the catalog, optionally by category",
        parameters={
            "category": {"type": "string", "description": "Filter by category (coding, automation, unique, voice, channel)", "required": False},
        },
        handler=plugin_catalog_browse,
        category="plugins",
        timeout=30,
    ))

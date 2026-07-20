from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from loguru import logger

from raven.unique.plugin_marketplace import PluginCatalog, PluginManager

_catalog = PluginCatalog()
_manager = PluginManager()


def create_plugin_router() -> APIRouter:
    router = APIRouter(prefix="/api/plugins", tags=["plugins"])

    @router.get("")
    def api_plugins_list():
        installed = _manager.list_installed()
        return [
            {
                "id": p.metadata.id,
                "name": p.metadata.name,
                "version": p.metadata.version,
                "description": p.metadata.description,
                "author": p.metadata.author,
                "category": p.metadata.category.value,
                "status": p.status.value,
                "install_path": str(p.install_path),
                "installed_at": p.installed_at,
            }
            for p in installed
        ]

    @router.get("/catalog")
    async def api_plugins_catalog(category: str = ""):
        await _catalog.sync()
        plugins = list(_catalog._plugins.values())
        if category:
            plugins = [p for p in plugins if p.category.value == category]
        return [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "tags": p.tags,
                "category": p.category.value,
                "icon": p.icon,
            }
            for p in plugins
        ]

    @router.get("/search")
    async def api_plugins_search(q: str = ""):
        if not q:
            return []
        await _catalog.sync()
        results = _catalog.search(q)
        return [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "tags": p.tags,
                "category": p.category.value,
            }
            for p in results
        ]

    @router.post("/install")
    async def api_plugins_install(body: dict[str, Any]):
        url_or_path = body.get("url", "") or body.get("path", "")
        source = body.get("source", "remote")
        if not url_or_path:
            return {"error": "url or path required"}
        try:
            result = await _manager.install_plugin(url_or_path, source=source)
            return {
                "ok": True,
                "name": result.metadata.name,
                "version": result.metadata.version,
                "status": result.status.value,
            }
        except Exception as e:
            logger.exception("plugin install failed")
            return {"error": str(e)}

    @router.post("/uninstall/{name}")
    async def api_plugins_uninstall(name: str):
        try:
            ok = await _manager.uninstall_plugin(name)
            return {"ok": ok}
        except Exception as e:
            return {"error": str(e)}

    @router.post("/update/{name}")
    async def api_plugins_update(name: str):
        try:
            result = await _manager.update_plugin(name)
            return {
                "ok": True,
                "name": result.metadata.name,
                "version": result.metadata.version,
                "status": result.status.value,
            }
        except Exception as e:
            return {"error": str(e)}

    @router.get("/top")
    async def api_plugins_top(limit: int = 10):
        await _catalog.sync()
        top = _catalog.get_top_rated(limit)
        return [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "rating": rating,
                "category": p.category.value,
            }
            for p, rating in top
        ]

    return router

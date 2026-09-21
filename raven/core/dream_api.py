from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from loguru import logger

from raven.core.dreaming.engine import DreamEngine

if TYPE_CHECKING:
    from raven.core.memory.manager import MemoryManager


async def _get_memory_stats(mgr: MemoryManager) -> dict[str, Any]:
    tiers = {}
    for tier_name in ("working", "session", "long_term", "knowledge"):
        store = getattr(mgr, tier_name, None)
        if store is None:
            continue
        try:
            keys = await store.list_keys() if hasattr(store, "list_keys") else []
            tiers[tier_name] = len(keys)
        except Exception as e:
            logger.debug("Memory stats for '{}' failed: {}", tier_name, e)
            tiers[tier_name] = 0
    return tiers


def _get_dream_skills() -> list[dict[str, Any]]:
    from raven.core.skills import list_skills

    return [s for s in list_skills() if s.get("source") == "dream"]


def create_dream_router(memory_manager: MemoryManager) -> APIRouter:
    router = APIRouter()

    @router.get("/api/dream/status")
    async def api_dream_status(request: Request):
        eng: DreamEngine = request.app.state.dream_engine
        return eng.status()

    @router.get("/api/dream/stats")
    async def api_dream_stats(request: Request):
        eng: DreamEngine = request.app.state.dream_engine
        memory_stats = await _get_memory_stats(memory_manager)
        dream_skills = _get_dream_skills()
        return {
            **eng.status(),
            "memory": memory_stats,
            "skills": dream_skills,
        }

    @router.post("/api/dream/cycle")
    async def api_dream_cycle(request: Request):
        eng: DreamEngine = request.app.state.dream_engine
        stats = await eng.cycle_once()
        return {"ok": True, "stats": stats}

    @router.post("/api/memory/backup")
    async def api_memory_backup():
        from raven.core.backup import export_memory

        path = await export_memory(memory_manager)
        return {"ok": True, "path": str(path)}

    @router.post("/api/memory/restore")
    async def api_memory_restore(body: dict[str, str]):
        from raven.core.backup import import_memory
        from raven.core.security.path_guard import confine_path

        data_dir = Path("data").resolve()
        raw = Path(body.get("path", ""))
        try:
            source = confine_path(str(raw), data_dir)
        except PermissionError:
            return {"ok": False, "error": "Access denied: path outside data directory"}
        if not source.is_file():
            return {"ok": False, "error": f"File not found: {source}"}
        try:
            counts = await import_memory(memory_manager, source)
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "restored": counts}

    @router.get("/api/memory/backups")
    async def api_memory_backups():
        from raven.core.backup import list_backups

        backups = await list_backups()
        return {"backups": backups}

    return router

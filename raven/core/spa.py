from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger


def mount_spa(app: FastAPI, web_dist: Path) -> bool:
    """Serve the built React SPA. Must be called LAST so /api/* routes win the catch-all."""
    if not web_dist.is_dir():
        logger.info("Web dashboard not built (no {}). Run cd web && npm install && npm run build", web_dist)
        return False

    assets_dir = web_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(str(web_dist / "index.html"))

    logger.info("Web dashboard mounted from {}", web_dist)
    return True

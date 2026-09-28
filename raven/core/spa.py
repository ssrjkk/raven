from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

WEB_DIST_ENV_VAR = "RAVEN_WEB_DIST"


def _candidate_dirs() -> list[Path]:
    """Every location that may hold the built SPA, most specific first."""
    candidates: list[Path] = []
    override = os.getenv(WEB_DIST_ENV_VAR, "").strip()
    if override:
        candidates.append(Path(override))
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "web" / "dist")
    package_root = Path(__file__).resolve().parents[1]  # raven/ — wheel installs stage assets here
    candidates.append(package_root / "web" / "dist")
    candidates.append(package_root.parent / "web" / "dist")  # repo checkout / _MEIPASS
    candidates.append(Path.cwd() / "web" / "dist")
    for entry in sys.path:
        if entry:
            candidates.append(Path(entry) / "web" / "dist")
    return candidates


def resolve_web_dist() -> Path | None:
    """Locate the built React SPA (``web/dist``) for source checkouts, wheels and PyInstaller bundles."""
    for candidate in _candidate_dirs():
        if (candidate / "index.html").is_file():
            return candidate
    return None


def mount_spa(app: FastAPI, web_dist: Path | None) -> bool:
    """Serve the built React SPA. Must be called LAST so /api/* routes win the catch-all."""
    if web_dist is None or not web_dist.is_dir():
        logger.info(
            "Web dashboard not built ({}). Run cd web && npm install && npm run build",
            web_dist or "no web/dist found",
        )
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

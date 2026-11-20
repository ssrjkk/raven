from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

WEB_DIST_ENV_VAR = "RAVEN_WEB_DIST"

BUNDLE_SERVED_ATTR = "raven_serves_bundle_files"
"""The one marker the request budget reads: a handler carrying it answers with bytes the server already holds.

That is a file from the built bundle (`/assets`, a font, the worker) or the document that boots the interface
(`mount_spa`'s catch-all and the webchat page at `/`, which is that file plus a canary) -- nothing that reaches
the datastore, the model or the network.

`raven.core.middleware.rate_limit_middleware` asks the router which handler a request lands on and exempts it
only when this attribute is present, so serving the bundle never spends the API budget while every dynamic
route keeps spending it -- including routes added later, which are charged until someone declares otherwise.
"""


class BundleFiles(StaticFiles):
    """The built SPA's own files, declared as the one surface the request budget must not spend on."""

    raven_serves_bundle_files = True


BUNDLE_MEDIA_TYPES: dict[str, str] = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".map": "application/json",
    ".webmanifest": "application/manifest+json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/vnd.microsoft.icon",
    ".txt": "text/plain",
}
"""What the files beside ``assets/`` are, announced to the browser rather than inferred.

Firefox refuses an ``@font-face`` whose response is not typed as a font, and on this interpreter
``mimetypes.guess_type`` answers ``(None, None)`` for ``.woff2``, ``.woff``, ``.ttf`` and ``.otf``, so the
fallback for a served-but-untyped face is ``application/octet-stream``. The registry a Windows host
publishes is a second, unrelated answer to the same question and Linux CI does know ``font/woff2``, so
without this table the promise would hold on the runner and break on the operator's machine.

The same reason decides ``.ico``: ``image/x-icon`` is what this host's registry publishes and
``image/vnd.microsoft.icon`` is the registered type the SPA shell, the offline shell and the web chat page all
announce in their ``<link rel="icon" type=...>``, so the table names what the documents promise rather than
what one platform's registry happens to say."""


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


def bundle_file(web_dist: Path, full_path: str) -> Path | None:
    """The file inside the bundle that a request path names, or None when it names a route instead.

    `resolve()` is what makes the escape attempts miss: it follows every symlink and collapses `..`, and the
    result has to sit under the resolved bundle root, so a link planted inside `web/dist` cannot hand back a
    file outside it.
    """
    root = web_dist.resolve()
    target = (root / full_path).resolve()
    if target == root or not target.is_relative_to(root):
        return None
    return target if target.is_file() else None


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
        app.mount("/assets", BundleFiles(directory=str(assets_dir)), name="assets")

    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        served = bundle_file(web_dist, full_path)
        if served is not None:
            return FileResponse(str(served), media_type=BUNDLE_MEDIA_TYPES.get(served.suffix.lower()))
        return FileResponse(str(web_dist / "index.html"), media_type="text/html")

    # The catch-all answers a deep link (`/monitors`) with the shell, which is as much a file as `/sw.js`, so
    # it carries the same declaration the budget reads.
    setattr(spa_fallback, BUNDLE_SERVED_ATTR, True)
    app.get("/{full_path:path}", include_in_schema=False)(spa_fallback)

    logger.info("Web dashboard mounted from {}", web_dist)
    return True

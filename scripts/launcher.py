"""Raven Desktop launcher — runs the gateway + bundled web UI as one app.

Frozen with PyInstaller (see scripts/build_exe.ps1). On start it:
  1. Resolves a writable data dir (next to the EXE, or RAVEN_DATA_DIR override).
  2. Redirects DB / logs / workspace into that dir via environment variables
     BEFORE importing ``raven`` so pydantic-settings picks up absolute paths.
  3. Boots the Raven gateway (same code path as ``raven start``).
  4. Opens the browser to the web dashboard.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _resolve_exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resolve_data_dir() -> Path:
    override = os.environ.get("RAVEN_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return _resolve_exe_dir()


def _configure_env(data_dir: Path) -> None:
    for sub in ("data", "logs", "workspace"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DB_PATH", str(data_dir / "data" / "raven.db"))
    os.environ.setdefault("LOG_FILE", str(data_dir / "logs" / "raven.log"))
    os.environ.setdefault("WORKSPACE_PATH", str(data_dir / "workspace"))
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.chdir(data_dir)


def _open_browser(url: str) -> None:
    def _open() -> None:
        import contextlib
        import time

        time.sleep(2.5)
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Raven Desktop — gateway + web UI")
    parser.add_argument("--port", type=int, default=None, help="Web UI port (default: 18888)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    parser.add_argument("--ghost", action="store_true", help="100% offline mode (local LLM only)")
    args = parser.parse_args()

    data_dir = _resolve_data_dir()
    _configure_env(data_dir)

    # Env is set before importing raven so Settings reads redirected paths.
    from loguru import logger

    from raven.cli.gateway_runner import _run_gateway, create_gateway
    from raven.core.config import settings

    if args.ghost:
        from raven.core.config import apply_ghost_mode

        apply_ghost_mode()

    web_port = args.port or settings.web_port
    logger.info("Raven Desktop starting — data dir: {}", data_dir)
    logger.info("Web UI: http://localhost:{}/", web_port)

    if not args.no_browser:
        _open_browser(f"http://localhost:{web_port}/")

    gateway = create_gateway()
    asyncio.run(_run_gateway(gateway, web_port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

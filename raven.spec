# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Raven AI Windows executable.

Usage:
    pyinstaller build/raven.spec

To replace the mascot icon:
    1. Place your .ico file at resources/raven.ico
    2. Update the `icon` parameter below
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent

a = Analysis(
    [str(ROOT / "raven" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "raven" / "plugins"), "raven/plugins"),
    ],
    hiddenimports=[
        # Core modules
        "raven",
        "raven.core",
        "raven.core.config",
        "raven.core.db",
        "raven.core.models",
        "raven.core.llm",
        "raven.core.plugin_loader",
        "raven.core.task_queue",
        "raven.core.agent",
        "raven.core.agent.agent",
        "raven.core.agent.registry",
        "raven.core.gateway",
        "raven.core.gateway.gateway",
        "raven.core.plugins",
        "raven.core.channels",
        # CLI
        "raven.cli",
        "raven.cli.main",
        # Channels
        "raven.channels",
        "raven.channels.base",
        "raven.channels.telegram",
        "raven.channels.telegram.channel",
        "raven.channels.discord",
        "raven.channels.discord.channel",
        "raven.channels.webchat",
        "raven.channels.webchat.channel",
        # Plugins
        "raven.plugins.memory",
        "raven.plugins.memory.plugin",
        "raven.plugins.browser",
        "raven.plugins.browser.plugin",
        "raven.plugins.cron",
        "raven.plugins.cron.plugin",
        "raven.plugins.code",
        "raven.plugins.code.plugin",
        "raven.plugins.files",
        "raven.plugins.files.plugin",
        "raven.plugins.api",
        "raven.plugins.api.plugin",
        "raven.plugins.ocr",
        "raven.plugins.ocr.plugin",
        "raven.plugins.process",
        "raven.plugins.process.plugin",
        # Third-party hidden imports
        "pkg_resources",
        "pkgutil",
        "asyncio",
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http.auto",
        "uvicorn.middleware",
        "uvicorn.middleware.wsgi",
        "fastapi",
        "fastapi.routing",
        "websockets",
        "websockets.legacy",
        "httpx",
        "aiosqlite",
        "pydantic",
        "pydantic_settings",
        "click",
        "rich",
        "rich.markdown",
        "rich.table",
        "rich.panel",
        "loguru",
        "apscheduler",
        "apscheduler.triggers",
        "apscheduler.triggers.cron",
        "chromadb",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "sympy",
        "PIL",
        "cv2",
        "torch",
        "tensorflow",
        "notebook",
        "jupyter",
        "ipython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="raven",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    icon=str(ROOT / "resources" / "raven.ico") if (ROOT / "resources" / "raven.ico").exists() else None,
)

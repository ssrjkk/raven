#!/usr/bin/env python3
"""Build Raven AI as a single EXE using PyInstaller + Go compilation."""

import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DIST = BASE / "dist"

_SHIM = {"go": shutil.which("go") or "go", "npm": shutil.which("npm") or "npm"}


def build_go_services() -> None:
    print("==> Building Go services...")
    DIST.mkdir(parents=True, exist_ok=True)
    services = [
        ("services/gateway", "gateway.exe"),
        ("services/auth", "auth.exe"),
        ("services/monitor-engine", "monitor-engine.exe"),
    ]
    for srcdir, outname in services:
        src = BASE / srcdir
        out = DIST / outname
        print(f"  go build {srcdir} -> {out}")
        result = subprocess.run(  # noqa: S603 — args hardcoded
            [_SHIM["go"], "build", "-o", str(out), "."],
            cwd=str(src),
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  [WARN] Go build failed for {srcdir}: {result.stderr}")
        else:
            print(f"  [OK] {outname}")


def build_web() -> None:
    web_dir = BASE / "web"
    if (web_dir / "dist").exists():
        print("==> Web dist already built, skipping npm build")
        return
    print("==> Building web frontend...")
    result = subprocess.run(  # noqa: S603 — args hardcoded
        [_SHIM["npm"], "install"], cwd=str(web_dir), capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"  [WARN] npm install failed: {result.stderr}")
        return
    result = subprocess.run(  # noqa: S603 — args hardcoded
        [_SHIM["npm"], "run", "build"], cwd=str(web_dir), capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"  [WARN] npm build failed: {result.stderr}")
    else:
        print("  [OK] web/dist built")


def build_pyinstaller() -> None:
    print("==> Building PyInstaller EXE...")
    spec_path = DIST / "raven-ai.spec"
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

block_cipher = None

datas = []

# web dist
web_dist = Path(__file__).parent.parent / "web" / "dist"
if web_dist.is_dir():
    for f in web_dist.rglob("*"):
        if f.is_file():
            rel = f.relative_to(web_dist.parent)
            datas.append((str(f), str(rel.parent)))

a = Analysis(
    ['main.py'],
    pathex=[str(Path(__file__).parent.parent)],
    binaries=[],
    datas=datas + [
        ('.opencode', '.opencode'),
        ('.ravencode', '.ravencode'),
    ],
    hiddenimports=[
        'fastapi', 'uvicorn', 'httpx', 'loguru', 'click', 'rich',
        'nats', 'pydantic', 'apscheduler', 'docker',
        'raven', 'ravencode', 'aios',
        'raven.channels', 'raven.core', 'raven.cli', 'raven.plugins', 'raven.tools',
        'ravencode.runtime', 'ravencode.api',
        'services.observability_sdk',
        'multipart', 'watchfiles', 'orjson',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'PIL', 'cv2', 'torch', 'tensorflow',
        'notebook', 'jupyter', 'ipython', 'setuptools', 'pip',
        'test', 'tests', 'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='raven-ai',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    spec_path.write_text(spec_content, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 — sys.executable is trusted
        [sys.executable, "-m", "PyInstaller", str(spec_path)],
        cwd=str(BASE), capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  [FAIL] PyInstaller failed: {result.stderr}")
        print(result.stdout)
        return
    exe_path = BASE / "dist" / "raven-ai.exe"
    if exe_path.exists():
        size = exe_path.stat().st_size // (1024 * 1024)
        print(f"  [OK] raven-ai.exe ({size} MB)")
    else:
        print("  [WARN] raven-ai.exe not found, checking dist/")


def main() -> None:
    print("=" * 50)
    print("  Raven AI EXE Builder")
    print("=" * 50)
    build_web()
    build_pyinstaller()
    print("Done. EXE available at dist/raven-ai.exe" if (BASE / "dist" / "raven-ai.exe").exists()
          else "Done. Check dist/ for output.")


if __name__ == "__main__":
    main()

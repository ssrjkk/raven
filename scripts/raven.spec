# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Raven Desktop EXE (gateway + bundled web UI).

Build:  powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH == scripts/, parent == repo root

# Plugins are loaded dynamically via PluginLoader — collect all submodules.
hiddenimports: list[str] = []
for _mod in ("raven.plugins", "raven.monitors", "raven.routines", "raven.tools", "raven.unique"):
    hiddenimports += collect_submodules(_mod)
for _mod in ("aios", "ravencode"):
    hiddenimports += collect_submodules(_mod)

datas: list[tuple[str, str]] = [
    (str(ROOT / "web" / "dist"), "web/dist"),
    (str(ROOT / "plugins"), "plugins"),
]
# gateway_runner loads plugins from Path(__file__).parent.parent / "plugins",
# which in the onefile bundle resolves to <tmp>/raven/plugins. Ship the plugin
# package dirs (with their plugin.py files) as real files under raven/plugins.
_plugins_src = ROOT / "raven" / "plugins"
if _plugins_src.is_dir():
    datas.append((str(_plugins_src / "__init__.py"), "raven/plugins"))
    for _p in sorted(_plugins_src.iterdir()):
        if _p.is_dir() and _p.name != "__pycache__":
            datas.append((str(_p), f"raven/plugins/{_p.name}"))
for _mod in ("raven.monitors", "raven.routines"):
    datas += collect_data_files(_mod)

# Optional extras that are guarded by try/except ImportError in the codebase.
# Excluding them keeps the EXE small; those features simply degrade gracefully.
excludes = [
    "accelerate", "bitsandbytes", "capstone", "chromadb", "datasets", "docker",
    "numba", "onnxruntime", "peft", "pefile", "playwright", "pyelftools",
    "safetensors", "sentence_transformers", "sounddevice", "spacy", "textual",
    "tokenizers", "torch", "transformers", "y_py", "y_py_ext", "_tkinter",
]

a = Analysis(
    [str(ROOT / "scripts" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Raven",
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
    icon=str(ROOT / "scripts" / "raven.ico"),
)

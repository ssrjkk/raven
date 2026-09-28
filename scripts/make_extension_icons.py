"""Generate PNG icons for the browser extension and the VS Code extension.

The Chrome MV3 manifest (``extension/manifest.json``) references
``icons/icon{16,48,128}.png`` and the VS Code manifest
(``extension/vscode/package.json``) references ``icon.png``. Both are produced
here from the shared renderer in ``scripts/icon_render.py``.

Usage:
    python scripts/make_extension_icons.py            # write missing icons only
    python scripts/make_extension_icons.py --force    # regenerate every icon
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from icon_render import render_icon

ROOT = Path(__file__).resolve().parent.parent
BROWSER_ICON_DIR = ROOT / "extension" / "icons"
BROWSER_SIZES = (16, 48, 128)
VSCODE_ICON = ROOT / "extension" / "vscode" / "icon.png"
VSCODE_SIZE = 256


def write_png(path: Path, size: int, force: bool) -> bool:
    """Write a PNG icon; returns True when the file was (re)written."""
    if path.exists() and not force:
        print(f"icon already present: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    render_icon(size).save(path, format="PNG")
    print(f"icon written: {path} ({size}x{size})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Raven extension icons")
    parser.add_argument("--force", action="store_true", help="Regenerate icons even if they exist")
    args = parser.parse_args()

    written = 0
    for size in BROWSER_SIZES:
        written += write_png(BROWSER_ICON_DIR / f"icon{size}.png", size, args.force)
    written += write_png(VSCODE_ICON, VSCODE_SIZE, args.force)

    print(f"done: {written} icon(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())

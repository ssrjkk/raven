"""Generate scripts/raven.ico for the PyInstaller build if it does not exist."""
from __future__ import annotations

import sys
from pathlib import Path

from icon_render import render_icon

SIZE = 256
OUT = Path(__file__).parent / "raven.ico"


def main() -> int:
    if OUT.exists():
        print(f"icon already present: {OUT}")
        return 0

    img = render_icon(SIZE)
    img.save(OUT, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"icon written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

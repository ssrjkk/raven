"""Generate scripts/raven.ico for the PyInstaller build from the brand mark the site ships."""

from __future__ import annotations

import sys
from pathlib import Path

from icon_render import render_icon

OUT = Path(__file__).parent / "raven.ico"
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def main() -> int:
    # Written every run: skipping an existing file is how the executable kept shipping the old bird.
    render_icon(max(size for size, _ in SIZES)).save(OUT, format="ICO", sizes=SIZES)
    print(f"icon written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

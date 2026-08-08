"""Generate scripts/raven.ico for the PyInstaller build if it does not exist."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
OUT = Path(__file__).parent / "raven.ico"


def _rounded_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill: tuple[int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def main() -> int:
    if OUT.exists():
        print(f"icon already present: {OUT}")
        return 0

    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Vertical accent gradient background (violet -> indigo).
    top = (124, 58, 237)
    bottom = (79, 70, 229)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (SIZE, y)], fill=color + (255,))

    # Rounded-square mask so the gradient follows the rounded corners.
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=56, fill=255)
    img.putalpha(mask)

    # White stylized bird: two overlapping ellipses (body + head).
    body = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(body).ellipse([46, 96, 200, 196], fill=(255, 255, 255, 255))
    ImageDraw.Draw(body).ellipse([128, 48, 224, 130], fill=(255, 255, 255, 255))
    # Beak.
    ImageDraw.Draw(body).polygon([(196, 96), (232, 60), (198, 66)], fill=(255, 224, 130, 255))
    img.alpha_composite(body)

    img.save(OUT, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"icon written: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

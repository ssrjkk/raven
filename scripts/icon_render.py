"""Shared renderer for the Raven bird icon.

Used by ``make_icon.py`` (Windows ``.ico`` for PyInstaller) and
``make_extension_icons.py`` (PNG assets for the browser and VS Code extensions)
so every shipped icon comes from a single source of truth.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

BASE = 256
TOP = (124, 58, 237)
BOTTOM = (79, 70, 229)
BEAK = (255, 224, 130, 255)
WHITE = (255, 255, 255, 255)


def render_icon(size: int) -> Image.Image:
    """Render the Raven icon at ``size``x``size`` pixels (violet→indigo tile with a white bird)."""
    if size < 8:
        msg = f"icon size must be >= 8, got {size}"
        raise ValueError(msg)

    scale = size / BASE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Vertical accent gradient background (violet -> indigo).
    for y in range(size):
        t = y / (size - 1)
        color = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=(*color, 255))

    # Rounded-square mask so the gradient follows the rounded corners.
    radius = round(56 * scale)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.putalpha(mask)

    # White stylized bird: two overlapping ellipses (body + head) plus a beak.
    bird = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bird_draw = ImageDraw.Draw(bird)
    bird_draw.ellipse(_scaled((46, 96, 200, 196), scale), fill=WHITE)
    bird_draw.ellipse(_scaled((128, 48, 224, 130), scale), fill=WHITE)
    beak = ((196, 96), (232, 60), (198, 66))
    bird_draw.polygon([_scaled(point, scale) for point in beak], fill=BEAK)
    img.alpha_composite(bird)
    return img


def _scaled(values: tuple[int, ...], scale: float) -> tuple[int, ...]:
    return tuple(round(value * scale) for value in values)

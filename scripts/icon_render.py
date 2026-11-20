"""Raster the Raven brand mark from the vector the site ships.

``site/favicon.svg`` is the one drawing of the mark. The browser extension, the VS Code
extension, the Windows executable and the installable app each ship a raster icon, and those
PNG/ICO files used to be drawn by hand here from a different bird — so the product looked like
another brand wherever the operating system drew it. Now every raster is a scaled render of the
vector, which means editing the mark reaches all of them.

Used by ``make_icon.py`` (the ``.ico`` for PyInstaller), ``make_extension_icons.py`` (the PNG
assets) and ``make_web_icons.py`` (the installable app's favicon, manifest tiles and notification
art), which are the intended callers.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
MARK_SVG = ROOT / "site" / "favicon.svg"

# Polygons are drawn at this multiple of the target and downscaled, because PIL fills edges hard.
SUPERSAMPLE = 4

_COMMAND = re.compile(r"[MmLlHhVvZz]")
_TOKEN = re.compile(r"[MmLlHhVvZz]|-?\d*\.?\d+")
_PATH_TAG = re.compile(r"<path\b[^>]*>")
_GROUP_TAG = re.compile(r"<(/?)g\b([^>]*)>")
_FUNC = re.compile(r"(translate|scale)\(([^)]*)\)")
_D = re.compile(r'\bd="([^"]+)"')
_FILL = re.compile(r'fill="([^"]+)"')
_RECT = re.compile(r"<rect\b[^>]*>")
_VIEW_BOX = re.compile(r'viewBox="([^"]+)"')

RGBA = tuple[int, int, int, int]
Point = tuple[float, float]
# p' = p * scale + offset, the affine part of the transforms this renderer understands.
Transform = tuple[Point, Point]


def _points(d: str) -> list[Point]:
    """Outline a path as polygon vertices.

    Only the straight-line grammar the mark actually uses is understood (M/L/H/V/Z, absolute
    or relative). A curve command is refused rather than flattened into a chord, which would
    raster a mark that quietly stops matching the vector.
    """
    if re.search(r"[CcSsQqTtAa]", d):
        msg = f"the brand mark must stay polygon-only, a curve command appears in {d!r}"
        raise ValueError(msg)
    tokens = _TOKEN.findall(d)
    points: list[Point] = []
    cursor: Point = (0.0, 0.0)
    origin: Point = (0.0, 0.0)
    index = 0
    while index < len(tokens):
        head = tokens[index]
        index += 1
        letter = head.upper()
        if letter == "Z":
            cursor = origin
            continue
        absolute = head.isupper()
        numbers: list[float] = []
        while index < len(tokens) and not _COMMAND.fullmatch(tokens[index]):
            numbers.append(float(tokens[index]))
            index += 1
        step = 1 if letter in {"H", "V"} else 2
        if len(numbers) % step:
            msg = f"path {d!r} leaves a coordinate over after {head}"
            raise ValueError(msg)
        for offset in range(0, len(numbers) - step + 1, step):
            chunk = numbers[offset : offset + step]
            if letter == "H":
                cursor = (chunk[0] if absolute else cursor[0] + chunk[0], cursor[1])
            elif letter == "V":
                cursor = (cursor[0], chunk[0] if absolute else cursor[1] + chunk[0])
            else:
                x, y = chunk
                if not absolute:
                    x += cursor[0]
                    y += cursor[1]
                cursor = (x, y)
                # Only the first pair of an M moves the pen; the rest are implicit line-tos.
                if letter == "M" and offset == 0:
                    origin = cursor
            points.append(cursor)
    if not points:
        msg = f"path {d!r} drew nothing"
        raise ValueError(msg)
    return points


def _apply(transform: Transform, point: Point) -> Point:
    (sx, sy), (ox, oy) = transform
    return (point[0] * sx + ox, point[1] * sy + oy)


def _compose(transform: Transform, function: str, args: list[float]) -> Transform:
    """Add a transform function to the right of the ones already collected."""
    (sx, sy), (ox, oy) = transform
    if function == "translate":
        tx, ty = args[0], args[1] if len(args) > 1 else 0.0
        return ((sx, sy), (ox + sx * tx, oy + sy * ty))
    if function == "scale":
        fx, fy = args[0], args[1] if len(args) > 1 else args[0]
        return ((sx * fx, sy * fy), (ox, oy))
    msg = f"transform {function}({args}) is not something the brand mark should need"
    raise ValueError(msg)


def _outer_then(inner: Transform, outer: Transform) -> Transform:
    """``outer`` wraps ``inner``, which is how an enclosing group acts on its children."""
    (is_x, is_y), (ix, iy) = inner
    (os_x, os_y), (ox, oy) = outer
    return ((os_x * is_x, os_y * is_y), (os_x * ix + ox, os_y * iy + oy))


def _transform_of(attributes: str) -> Transform:
    transform: Transform = ((1.0, 1.0), (0.0, 0.0))
    match = re.search(r'transform="([^"]+)"', attributes)
    if match is None:
        return transform
    for function, raw in _FUNC.findall(match.group(1)):
        transform = _compose(transform, function, [float(value) for value in raw.replace(",", " ").split()])
    return transform


def _svg_text(svg_text: str | None) -> str:
    return MARK_SVG.read_text(encoding="utf-8") if svg_text is None else svg_text


def mark_shapes(svg_text: str | None = None) -> list[tuple[list[Point], RGBA]]:
    """The drawn mark as (vertices, colour) pairs, in the coordinate space of its own viewBox."""
    text = _svg_text(svg_text)
    shapes: list[tuple[list[Point], RGBA]] = []
    stack: list[Transform] = []
    for match in re.finditer(f"{_GROUP_TAG.pattern}|{_PATH_TAG.pattern}", text):
        tag = match.group(0)
        if tag.startswith("<g") or tag.startswith("</g"):
            closing = tag[2] == "/"
            if closing:
                if not stack:
                    msg = "the brand mark closes a group it never opened"
                    raise ValueError(msg)
                stack.pop()
            else:
                stack.append(_transform_of(tag))
            continue
        d_match, fill_match = _D.search(tag), _FILL.search(tag)
        if d_match is None or fill_match is None:
            msg = f"a path of the brand mark has no geometry or no fill: {tag}"
            raise ValueError(msg)
        transform: Transform = ((1.0, 1.0), (0.0, 0.0))
        # Document order is outermost first, and a child is moved by its own transform before the group
        # around it moves it: each enclosing group therefore wraps the transform collected so far.
        for enclosing in stack:
            transform = _outer_then(enclosing, transform)
        vertices = [(_apply(transform, point)) for point in _points(d_match.group(1))]
        shapes.append((vertices, _colour(fill_match.group(1))))
    if not shapes:
        msg = f"{MARK_SVG} carries no drawn mark"
        raise ValueError(msg)
    return shapes


def plate(svg_text: str | None = None) -> tuple[RGBA, float]:
    """The background tile as (colour, corner radius), read from the vector's own ``<rect>``."""
    rect = _RECT.search(_svg_text(svg_text))
    if rect is None:
        msg = "the brand mark has no background tile to raster"
        raise ValueError(msg)
    fill_match, radius_match = _FILL.search(rect.group(0)), re.search(r'\brx="([^"]+)"', rect.group(0))
    if fill_match is None or radius_match is None:
        msg = f"the background tile needs a fill and a corner radius: {rect.group(0)}"
        raise ValueError(msg)
    return _colour(fill_match.group(1)), float(radius_match.group(1))


def canvas_size(svg_text: str | None = None) -> float:
    """The side length of the square the vector is authored in."""
    match = _VIEW_BOX.search(_svg_text(svg_text))
    if match is None:
        msg = f"{MARK_SVG} has no viewBox to size a raster against"
        raise ValueError(msg)
    _, _, width, height = [float(value) for value in match.group(1).replace(",", " ").split()]
    if width != height:
        msg = f"the brand mark must be square to raster a tile, viewBox says {width}x{height}"
        raise ValueError(msg)
    return width


def _colour(value: str) -> RGBA:
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) == 6:
        digits += "ff"
    if len(digits) != 8:
        msg = f"unreadable colour {value!r} in the brand mark"
        raise ValueError(msg)
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), int(digits[6:8], 16))


def render_icon(size: int, svg_text: str | None = None) -> Image.Image:
    """Render the brand mark at ``size``x``size`` pixels, corners transparent.

    ``svg_text`` overrides the shipped vector, which is how the parity guard proves it would notice a
    changed mark without rewriting the file it reads.
    """
    if size < 8:
        msg = f"icon size must be >= 8, got {size}"
        raise ValueError(msg)

    span = size * SUPERSAMPLE
    scale = span / canvas_size(svg_text)
    canvas = Image.new("RGBA", (span, span), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    background, radius = plate(svg_text)
    draw.rounded_rectangle([0, 0, span - 1, span - 1], radius=max(1, round(radius * scale)), fill=background)
    for vertices, colour in mark_shapes(svg_text):
        draw.polygon([_apply(((scale, scale), (0.0, 0.0)), point) for point in vertices], fill=colour)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)

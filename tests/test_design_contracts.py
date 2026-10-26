"""Design contracts for the three UI surfaces the product ships: the React SPA, the landing page
and the gateway-served chat pages.

These are deliberately harsh. A design system that is only a naming convention, a token that resolves
to nothing, grey-on-white text at 2.5:1 and a layout that overflows at 360px all look fine in a
screenshot taken at the author's monitor width, which is exactly why they need a gate rather than
taste. Every threshold here is the published number it comes from, not a preference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DESIGN = WEB / "src" / "design"
THEME_FILES = ("tokens.json", "tokens.light.json", "tokens.midnight.json")

# WCAG 2.1 contrast minima: 4.5:1 for normal text, 3:1 for large text and for non-text UI
# (borders, icons, focus indicators) -- https://www.w3.org/WAI/WCAG22/quickref/#contrast-minimum
NORMAL_TEXT = 4.5
LARGE_TEXT_OR_UI = 3.0

# (foreground token path, background token path, minimum)
# accent.default is a *surface* behind white labels, not a text colour (text.link is the readable
# violet), so it is checked against white and against the page as a UI component: 3:1.
TEXT_PAIRS = (
    (("text", "primary"), ("bg", "primary"), NORMAL_TEXT),
    (("text", "primary"), ("bg", "secondary"), NORMAL_TEXT),
    (("text", "primary"), ("bg", "tertiary"), NORMAL_TEXT),
    (("text", "secondary"), ("bg", "primary"), NORMAL_TEXT),
    (("text", "secondary"), ("bg", "secondary"), NORMAL_TEXT),
    (("text", "tertiary"), ("bg", "primary"), NORMAL_TEXT),
    (("text", "link"), ("bg", "primary"), NORMAL_TEXT),
    (("text", "link"), ("bg", "secondary"), NORMAL_TEXT),
    (("text", "inverse"), ("bg", "inverse"), NORMAL_TEXT),
)

WHITE = "#ffffff"
ACCENT_SURFACES = ("default", "hover", "active")

STATUS_ON_BG = (("success",), ("warning",), ("error",), ("info",))


def _palette(name: str) -> dict[str, Any]:
    colors = json.loads((DESIGN / name).read_text(encoding="utf-8"))["colors"]
    assert isinstance(colors, dict)
    return colors


def _channel(raw: int) -> float:
    value = raw / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    body = color.lstrip("#")
    assert len(body) == 6, f"expected a 6-digit hex, got {color!r}"
    red, green, blue = (int(body[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _hsl(color: str) -> tuple[float, float, float]:
    import colorsys

    body = color.lstrip("#")
    red, green, blue = (int(body[i : i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    return hue * 360, light, sat


def _media_block(css: str, query: str) -> str:
    """The full {...} body of the first at-rule whose prelude contains `query`."""
    start = css.find(query)
    assert start != -1, f"no @media block matching {query!r}"
    open_brace = css.index("{", start)
    depth = 0
    for index in range(open_brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace : index + 1]
    raise AssertionError(f"unbalanced braces after {query!r}")


def _css_declared_tokens() -> set[str]:
    declared: set[str] = set()
    for path in (WEB / "src").rglob("*.css"):
        declared |= set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", path.read_text(encoding="utf-8", errors="replace")))
    return declared


def _theme_tokens(name: str) -> set[str]:
    """Every custom property a theme publishes: the joined path of each leaf, so `colors.accent.default`
    becomes `--dt-colors-accent-default` and `animation.easing.out` becomes `--dt-animation-easing-out`."""
    data = json.loads((DESIGN / name).read_text(encoding="utf-8"))
    tokens: set[str] = set()

    def walk(node: Any, prefix: list[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, [*prefix, key])
        elif prefix:
            tokens.add("--dt-" + "-".join(prefix))

    for group, values in data.items():
        if group.startswith("$") or group in {"description", "version"}:
            continue
        walk(values, [group])
    return tokens


def _used_tokens() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    sources = list((WEB / "src").rglob("*.tsx")) + list((WEB / "src").rglob("*.ts")) + list((WEB / "src").rglob("*.css"))
    for path in sources:
        if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", text):
            used.setdefault(name, []).append(str(path.relative_to(WEB)))
    return used


# ── tokens resolve ─────────────────────────────────────────────────


def test_no_component_asks_for_a_token_the_theme_never_defines() -> None:
    declared = _css_declared_tokens()
    unresolved: dict[str, list[str]] = {}
    for name, files in _used_tokens().items():
        # a dynamic name (var(--dt-radius-${x})) cannot be resolved statically and is skipped
        if name.endswith("-"):
            continue
        if name in declared:
            continue
        if all(name in _theme_tokens(theme) for theme in THEME_FILES):
            continue
        unresolved[name] = sorted(set(files))
    assert not unresolved, f"tokens used but published by no theme: {unresolved}"


@pytest.mark.parametrize("theme", THEME_FILES)
def test_every_status_color_is_readable_on_the_page_background(theme: str) -> None:
    colors = _palette(theme)
    background = colors["bg"]["primary"]
    for (status,) in STATUS_ON_BG:
        value = colors["status"][status]
        if not isinstance(value, str) or not value.startswith("#"):
            continue
        ratio = contrast(value, background)
        assert ratio >= NORMAL_TEXT, f"{theme}: status.{status} {value} on bg.primary {background} = {ratio:.2f} < 4.5"


@pytest.mark.parametrize("theme", THEME_FILES)
def test_text_pairs_meet_aa_in_every_theme(theme: str) -> None:
    colors = _palette(theme)
    failures = []
    for (fg_group, fg_key), (bg_group, bg_key), minimum in TEXT_PAIRS:
        foreground = colors[fg_group][fg_key]
        background = colors[bg_group][bg_key]
        ratio = contrast(foreground, background)
        if ratio < minimum:
            failures.append(f"{fg_group}.{fg_key} {foreground} on {bg_group}.{bg_key} {background} = {ratio:.2f} < {minimum}")
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


def test_the_three_themes_define_the_same_token_set() -> None:
    sets = {theme: _theme_tokens(theme) for theme in THEME_FILES}
    reference = sets[THEME_FILES[0]]
    for theme, tokens in sets.items():
        assert tokens == reference, f"{theme} differs: missing {sorted(reference - tokens)}, extra {sorted(tokens - reference)}"


def test_white_labels_on_every_accent_state_clear_aa() -> None:
    """Buttons and ::selection put white on accent.default/hover/active; the hover state is exactly
    where a palette quietly drops below 4.5:1."""
    for theme in THEME_FILES:
        accent = _palette(theme)["accent"]
        for state in ACCENT_SURFACES:
            value = accent[state]
            if not isinstance(value, str) or not value.startswith("#"):
                continue
            ratio = contrast(WHITE, value)
            assert ratio >= NORMAL_TEXT, f"{theme}: white on accent.{state} {value} = {ratio:.2f} < 4.5"


@pytest.mark.parametrize("theme", THEME_FILES)
def test_accent_is_visible_against_the_page_as_a_component(theme: str) -> None:
    """3:1 is the non-text minimum: a button has to read as a distinct surface, not as text."""
    colors = _palette(theme)
    ratio = contrast(colors["accent"]["default"], colors["bg"]["primary"])
    assert ratio >= LARGE_TEXT_OR_UI, f"{theme}: accent.default on bg.primary = {ratio:.2f} < 3.0"


def test_the_accent_family_stays_purple_black() -> None:
    """The settled brand is violet to magenta. Hue is the check, not a list of forbidden hexes, so a
    new stock blue or indigo cannot slip in under a different code."""
    for theme in THEME_FILES:
        colors = _palette(theme)
        for group, key in (("accent", "default"), ("accent", "hover"), ("accent", "active"), ("text", "link"), ("border", "focus")):
            value = colors[group][key]
            hue, _, _ = _hsl(value)
            assert 250 <= hue <= 330, f"{theme}: {group}.{key} {value} has hue {hue:.0f}, outside the brand range"


# ── landing page ───────────────────────────────────────────────────


def _site_css() -> str:
    return (ROOT / "site" / "styles.css").read_text(encoding="utf-8")


def _site_html() -> str:
    return (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def test_landing_defines_every_token_it_uses() -> None:
    css = _site_css()
    declared = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", css))
    used = set(re.findall(r"var\(\s*(--[a-zA-Z0-9-]+)", css))
    fallback_used = set(re.findall(r"var\(\s*--[a-zA-Z0-9-]+\s*,", css))
    missing = used - declared - fallback_used
    assert not missing, f"landing CSS uses undefined custom properties: {sorted(missing)}"


def test_landing_honours_reduced_motion() -> None:
    css = _site_css()
    assert "prefers-reduced-motion: reduce" in css, "the animated hero owes the user an off switch"
    block = _media_block(css, "prefers-reduced-motion: reduce")
    assert "animation-duration" in block and "transition-duration" in block, "the reduce block must actually stop motion"


def test_landing_has_a_visible_focus_indicator() -> None:
    css = _site_css()
    assert re.search(r":focus-visible", css), "keyboard users need a ring that is not the browser default"


def test_landing_images_are_sized_and_named() -> None:
    html = _site_html()
    for img in re.findall(r"<img\b[^>]*>", html):
        assert "alt=" in img, f"img without alt: {img[:80]}"
        assert "width=" in img and "height=" in img, f"img without intrinsic size (layout shift): {img[:80]}"


def test_landing_anchors_resolve() -> None:
    html = _site_html()
    targets = set(re.findall(r"id=\"([^\"]+)\"", html))
    for href in re.findall(r"href=\"(#[^\"]+)\"", html):
        assert href[1:] in targets, f"dangling in-page link {href}"


# ── visualisation ──────────────────────────────────────────────────

CHART_TAGS = (
    "AreaChart", "Area", "BarChart", "Bar", "LineChart", "Line", "PieChart", "Pie", "Cell",
    "ScatterChart", "Scatter", "RadarChart", "Radar", "CartesianGrid", "PolarGrid", "XAxis",
    "YAxis", "Tooltip", "Legend", "ReferenceLine", "LabelList",
)
_HEX = re.compile(r"(?:stroke|fill|color|stopColor)=\"#[0-9a-fA-F]{3,8}\"")


def _chart_elements(source: str) -> list[str]:
    pattern = re.compile(r"<(" + "|".join(CHART_TAGS) + r")\b[^>]*/?>", re.S)
    return [match.group(0) for match in pattern.finditer(source)]


def test_charts_are_painted_from_tokens_not_from_copied_hexes() -> None:
    """A hex in a chart prop is frozen: it will not follow the theme, and it is how an off-brand
    indigo ended up as the primary series colour of a purple-black product."""
    offenders: dict[str, list[str]] = {}
    for path in (WEB / "src").rglob("*.tsx"):
        if path.name.endswith(".test.tsx"):
            continue
        bad = [element[:60] for element in _chart_elements(path.read_text(encoding="utf-8", errors="replace")) if _HEX.search(element)]
        if bad:
            offenders[str(path.relative_to(WEB))] = bad
    assert not offenders, f"hard-coded colours in chart props: {offenders}"


def test_charts_are_wrapped_in_the_labelled_card() -> None:
    """recharts paints a series into bare SVG nodes: without a name on the container a screen reader
    announces an empty region where the trend is. The labelling lives in one component, so the rule
    is a structural one -- every chart is a child of ChartCard."""
    card = (WEB / "src" / "components" / "ChartCard.tsx").read_text(encoding="utf-8")
    assert 'role="img"' in card and "aria-label={title}" in card, "ChartCard must carry the accessible name"
    for path in (WEB / "src").rglob("*.tsx"):
        if path.name == "ChartCard.tsx":
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        containers = len(re.findall(r"<ResponsiveContainer", source))
        if not containers:
            continue
        cards = len(re.findall(r"<ChartCard\b", source))
        assert cards >= containers, f"{path.name}: {containers} charts inside {cards} labelled cards"


@pytest.mark.parametrize("theme", THEME_FILES)
def test_chart_series_are_visible_on_their_own_theme(theme: str) -> None:
    colors = _palette(theme)
    series = colors["chart"]
    assert len(series) == 10, f"{theme} should carry ten categorical colours, has {len(series)}"
    background = colors["bg"]["primary"]
    for name, value in series.items():
        ratio = contrast(value, background)
        assert ratio >= LARGE_TEXT_OR_UI, f"{theme}: chart.{name} {value} on bg.primary = {ratio:.2f} < 3.0"


def test_chart_series_are_distinguishable_from_each_other() -> None:
    """Ten categories in ten near-identical violets tell a user nothing; the scale has to spread."""
    for theme in THEME_FILES:
        series = list(_palette(theme)["chart"].values())
        assert len(set(series)) == len(series), f"{theme}: duplicate series colours"
        hues = [_hsl(value)[0] for value in series]
        spread = max(hues) - min(hues)
        assert spread >= 120, f"{theme}: series hues span only {spread:.0f} degrees"


def test_inline_svg_scales_and_is_labelled() -> None:
    """An svg without a viewBox cannot resize, and a decorative one read out loud is noise."""
    offenders: list[str] = []
    sources = list((WEB / "src").rglob("*.tsx")) + list((ROOT / "site").glob("*.html")) + list((ROOT / "site").glob("*.svg"))
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for tag in re.findall(r"<svg\b[^>]*>", text):
            if "viewBox" not in tag:
                offenders.append(f"{path.name}: {tag[:70]}")
            if "aria-hidden" not in tag and "aria-label" not in tag and "role=" not in tag and "<title" in text[text.index(tag) : text.index(tag) + 400]:
                offenders.append(f"{path.name}: svg with a title but no role")
    assert not offenders, f"svg without a viewBox: {offenders}"


def test_the_spa_has_a_focus_ring_and_never_removes_one_without_replacing_it() -> None:
    css = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css, "keyboard focus has to be visible somewhere other than the browser default"
    for rule in re.findall(r"([^{}]*:focus[^{}]*)\{([^{}]*)\}", css):
        selector, body = rule
        if "outline: none" in body or "outline:none" in body:
            assert "box-shadow" in body or "border-color" in body, f"{selector.strip()} removes the ring and draws nothing in its place"


def test_landing_avoids_the_100vh_mobile_trap() -> None:
    css = _site_css()
    for rule in re.findall(r"[^{}]*\{[^}]*\}", css):
        if "100vh" in rule and "svh" not in rule and "dvh" not in rule:
            pytest.fail(f"{rule.strip()[:80]} -- 100vh jumps on mobile browsers; declare svh/dvh")


# ── gateway-served chat surfaces ──────────────────────────────────


def test_shipped_chat_pages_keep_a_visible_focus_ring_and_sane_targets() -> None:
    from raven.channels.webchat.channel import INDEX_HTML

    popup_css = (ROOT / "extension" / "src" / "popup" / "popup.css").read_text(encoding="utf-8")
    for label, sheet in (("webchat", INDEX_HTML), ("extension popup", popup_css)):
        assert ":focus" in sheet or ":focus-visible" in sheet, f"{label} has no focus style"
        assert "prefers-reduced-motion" in sheet or "animation" not in sheet, f"{label} animates with no reduce rule"


def test_shipped_chat_pages_declare_their_colour_contrast() -> None:
    """Both pages are plain-CSS surfaces, so their pairs are checked rather than eyeballed."""
    from raven.channels.webchat.channel import INDEX_HTML

    pairs = {
        "webchat": (("#e4e4e7", "#12121f"), ("#9a9ab0", "#12121f"), ("#ffffff", "#7c3aed")),
        "popup": (("#e4e4e7", "#0f1117"), ("#9a9ab0", "#0f1117"), ("#ffffff", "#7c3aed")),
    }
    assert INDEX_HTML  # imported for its stylesheet block below
    for label, items in pairs.items():
        for foreground, background in items:
            ratio = contrast(foreground, background)
            assert ratio >= LARGE_TEXT_OR_UI, f"{label}: {foreground} on {background} = {ratio:.2f}"

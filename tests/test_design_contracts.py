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
    # Labels on saturated fills: white is not one of these, it measures 1.67:1 on midnight warning.
    (("text", "on-accent"), ("accent", "default"), NORMAL_TEXT),
    (("text", "on-status-success"), ("status", "success"), NORMAL_TEXT),
    (("text", "on-status-warning"), ("status", "warning"), NORMAL_TEXT),
    (("text", "on-status-error"), ("status", "error"), NORMAL_TEXT),
    (("text", "on-status-info"), ("status", "info"), NORMAL_TEXT),
    # The label a category tag ships with: the hue is the ground, and the light theme darkens every hue for AA
    # on the page, which moves the label to the light side of the same pair.
    (("text", "on-category-blue"), ("category", "blue"), NORMAL_TEXT),
    (("text", "on-category-green"), ("category", "green"), NORMAL_TEXT),
    (("text", "on-category-amber"), ("category", "amber"), NORMAL_TEXT),
    (("text", "on-category-violet"), ("category", "violet"), NORMAL_TEXT),
    (("text", "on-category-pink"), ("category", "pink"), NORMAL_TEXT),
    (("text", "on-category-grey"), ("category", "grey"), NORMAL_TEXT),
    # The second stop of the brand gradient carries text in .gradient-text, so it needs text contrast.
    (("brand", "secondary"), ("bg", "primary"), NORMAL_TEXT),
    # Canvas text and canvas edges in the knowledge graph are painted from these, once a frame, and
    # so are chart tick labels: 9-11px text is normal text to WCAG, not a UI part.
    (("text", "secondary"), ("surface", "card"), NORMAL_TEXT),
    (("text", "tertiary"), ("surface", "card"), NORMAL_TEXT),
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
    sources = (
        list((WEB / "src").rglob("*.tsx")) + list((WEB / "src").rglob("*.ts")) + list((WEB / "src").rglob("*.css"))
    )
    for path in sources:
        if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", text):
            used.setdefault(name, []).append(str(path.relative_to(WEB)))
    return used


# ── tokens resolve ─────────────────────────────────────────────────


def tables_without_row_labels(html: str) -> list[str]:
    """Captions of tables that contain a data row starting with <td>.

    Below 520px the site hides <thead> and turns every row into a labelled block -- a sideways
    scroller that gives no hint it scrolls is worse than a second line -- so the row header is
    the only thing that keeps a phone reader knowing what a block describes."""
    offenders: list[str] = []
    for table in re.findall(r"<table>(.*?)</table>", html, re.S):
        match = re.search(r"<caption>(.*?)</caption>", table, re.S)
        caption = match.group(1).strip()[:40] if match else "(no caption)"
        for row in re.findall(r"<tr>\s*(.*?)</tr>", table, re.S):
            if row.lstrip().startswith("<td"):
                offenders.append(caption)
    return offenders


def test_every_data_table_carries_row_labels_the_mobile_layout_needs() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "site").glob("*.html")):
        if "404" in path.name:
            continue
        for caption in tables_without_row_labels(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}: {caption!r}")
    assert offenders == [], offenders


def test_the_row_label_guard_detects_the_layout_it_protects() -> None:
    broken = (
        '<table><caption>Example</caption><thead><tr><th scope="col">A</th>'
        '<th scope="col">B</th></tr></thead><tbody><tr><td>one</td><td>two</td></tr></tbody></table>'
    )
    assert tables_without_row_labels(broken) == ["Example"]
    labelled = broken.replace("<tr><td>one</td>", '<tr><th scope="row">one</th><td>')
    assert tables_without_row_labels(labelled) == []


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


_SHELL_SHEET = WEB / "src" / "styles" / "index.css"
_TOKEN_DECLARATION = re.compile(r"^\s*(--dt-[a-zA-Z0-9-]+)\s*:", re.M)


def test_the_console_sheet_declares_no_token_of_its_own() -> None:
    """Measured while retiring the last of them: the shell's own `:root` carried five status aliases and a
    `--dt-version: 1.0.0`, and no file in the tree read any of the six. A hand-written alias is a second
    scale the token files do not own, and the guard above cannot see it -- it asks whether a name a component
    reads is *declared* somewhere, and an alias declares itself, which is exactly how a name no theme
    publishes resolves while a recolour misses it. `themes.css` and `tailwind-theme.css` are generated from
    `tokens.json`; the sheet that is not generated declares nothing."""
    offenders = sorted(set(_TOKEN_DECLARATION.findall(_SHELL_SHEET.read_text(encoding="utf-8"))))
    assert offenders == [], f"{_SHELL_SHEET.relative_to(ROOT)} hand-declares tokens no theme publishes: {offenders}"


def test_the_shell_sheet_guard_reads_declarations_not_uses() -> None:
    planted = "  --dt-colors-success-default: var(--dt-colors-status-success);"
    assert _TOKEN_DECLARATION.findall(planted) == ["--dt-colors-success-default"]
    assert _TOKEN_DECLARATION.findall("  color: var(--dt-colors-accent-default);") == []
    assert _TOKEN_DECLARATION.findall("  --dt-version: 1.0.0;") == ["--dt-version"]


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
            failures.append(
                f"{fg_group}.{fg_key} {foreground} on {bg_group}.{bg_key} {background} = {ratio:.2f} < {minimum}"
            )
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


# The devices the storefront's language brings into the console lift a panel before any ink lands on it: a card
# is a translucent ramp, a selected nav item raises an accent chip under the violet it writes its label with, and
# a stat card catches the accent in its corner, exactly where its caption is. A role can clear AA on the flat
# token and fall under it on the lifted ground, so the grounds below are what gets measured.
INK_ROLES = ("primary", "secondary", "tertiary", "link")
PANELS = (("bg", "primary"), ("bg", "secondary"), ("surface", "card"))
LIFTS = ("subtle", "muted")


@pytest.mark.parametrize("theme", THEME_FILES)
def test_ink_roles_clear_aa_on_the_grounds_the_devices_lift(theme: str) -> None:
    colors = _palette(theme)
    grounds: dict[str, str] = {}
    for group, key in PANELS:
        panel = colors[group][key]
        grounds[f"{group}.{key}"] = panel
        for lift in LIFTS:
            grounds[f"{group}.{key} + accent.{lift}"] = _as_paint(colors["accent"][lift], panel)
    failures = []
    for role in INK_ROLES:
        ink = colors["text"][role]
        for name, ground in grounds.items():
            ratio = contrast(ink, ground)
            if ratio < NORMAL_TEXT:
                failures.append(f"text.{role} {ink} on {name} {ground} = {ratio:.2f} < {NORMAL_TEXT}")
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


# A status pill paints its own tint behind its own colour: the ink is the status, the ground is that same
# status at 10% over whichever panel the pill was dropped on. Checking the ink against the bare page hides the
# pair a reader actually sees -- every light-theme status ink shipped at 4.2-4.55:1 inside its own badge.
@pytest.mark.parametrize("theme", THEME_FILES)
def test_status_inks_clear_aa_on_their_own_tint(theme: str) -> None:
    colors = _palette(theme)
    status = colors["status"]
    failures = []
    for (name,) in STATUS_ON_BG:
        ink = status[name]
        for group, key in PANELS:
            ground = _as_paint(status[f"{name}-bg"], colors[group][key])
            ratio = contrast(ink, ground)
            if ratio < NORMAL_TEXT:
                failures.append(
                    f"status.{name} {ink} on {group}.{key} + its own tint {ground} = {ratio:.2f} < {NORMAL_TEXT}"
                )
    assert not failures, f"{theme}:\n  " + "\n  ".join(failures)


def test_the_three_themes_define_the_same_token_set() -> None:
    sets = {theme: _theme_tokens(theme) for theme in THEME_FILES}
    reference = sets[THEME_FILES[0]]
    for theme, tokens in sets.items():
        assert tokens == reference, (
            f"{theme} differs: missing {sorted(reference - tokens)}, extra {sorted(tokens - reference)}"
        )


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
        for group, key in (
            ("accent", "default"),
            ("accent", "hover"),
            ("accent", "active"),
            ("text", "link"),
            ("border", "focus"),
        ):
            value = colors[group][key]
            hue, _, _ = _hsl(value)
            assert 250 <= hue <= 330, f"{theme}: {group}.{key} {value} has hue {hue:.0f}, outside the brand range"


# ── landing page ───────────────────────────────────────────────────


def _site_css() -> str:
    return (ROOT / "site" / "styles.css").read_text(encoding="utf-8")


def _site_pages() -> dict[str, str]:
    site = ROOT / "site"
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(site.glob("*.html"))}


def _site_js() -> str:
    site = ROOT / "site"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(site.glob("*.js")))


def test_landing_declares_every_token_it_uses() -> None:
    """A `var(--x)` resolves in three legitimate ways: a CSS declaration, a value the scripts assign
    with `setProperty('--x', ...)`, or a fallback on the use itself. Anything else is a typo that
    renders as an empty value, which no screenshot at the author's width catches."""
    css = _site_css()
    declared = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", css))
    declared |= set(re.findall(r"setProperty\(\s*['\"](--[a-zA-Z0-9-]+)", _site_js()))
    used = set(re.findall(r"var\(\s*(--[a-zA-Z0-9-]+)", css))
    fallback_used = set(re.findall(r"var\(\s*(--[a-zA-Z0-9-]+)\s*,", css))
    missing = used - declared - fallback_used
    assert not missing, f"landing CSS uses undefined custom properties: {sorted(missing)}"


def test_landing_honours_reduced_motion() -> None:
    css = _site_css()
    assert "prefers-reduced-motion: reduce" in css, "the animated hero owes the user an off switch"
    block = _media_block(css, "prefers-reduced-motion: reduce")
    assert "animation-duration" in block and "transition-duration" in block, (
        "the reduce block must actually stop motion"
    )


def test_landing_has_a_visible_focus_indicator() -> None:
    css = _site_css()
    assert re.search(r":focus-visible", css), "keyboard users need a ring that is not the browser default"


def test_landing_images_are_sized_and_named() -> None:
    for name, html in _site_pages().items():
        for img in re.findall(r"<img\b[^>]*>", html):
            assert "alt=" in img, f"{name}: img without alt: {img[:80]}"
            assert "width=" in img and "height=" in img, (
                f"{name}: img without intrinsic size (layout shift): {img[:80]}"
            )


def test_landing_anchors_resolve() -> None:
    for name, html in _site_pages().items():
        targets = set(re.findall(r"id=\"([^\"]+)\"", html))
        for href in re.findall(r"href=\"(#[^\"]+)\"", html):
            assert href[1:] in targets, f"{name}: dangling in-page link {href}"


# ── visualisation ──────────────────────────────────────────────────

CHART_TAGS = (
    "AreaChart",
    "Area",
    "BarChart",
    "Bar",
    "LineChart",
    "Line",
    "PieChart",
    "Pie",
    "Cell",
    "ScatterChart",
    "Scatter",
    "RadarChart",
    "Radar",
    "CartesianGrid",
    "PolarGrid",
    "XAxis",
    "YAxis",
    "Tooltip",
    "Legend",
    "ReferenceLine",
    "LabelList",
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
        bad = [
            element[:60]
            for element in _chart_elements(path.read_text(encoding="utf-8", errors="replace"))
            if _HEX.search(element)
        ]
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
    sources = (
        list((WEB / "src").rglob("*.tsx")) + list((ROOT / "site").glob("*.html")) + list((ROOT / "site").glob("*.svg"))
    )
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        for tag in re.findall(r"<svg\b[^>]*>", text):
            if "viewBox" not in tag:
                offenders.append(f"{path.name}: {tag[:70]}")
            if (
                "aria-hidden" not in tag
                and "aria-label" not in tag
                and "role=" not in tag
                and "<title" in text[text.index(tag) : text.index(tag) + 400]
            ):
                offenders.append(f"{path.name}: svg with a title but no role")
    assert not offenders, f"svg without a viewBox: {offenders}"


def test_the_spa_has_a_focus_ring_and_never_removes_one_without_replacing_it() -> None:
    css = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    assert ":focus-visible" in css, "keyboard focus has to be visible somewhere other than the browser default"
    for rule in re.findall(r"([^{}]*:focus[^{}]*)\{([^{}]*)\}", css):
        selector, body = rule
        if "outline: none" in body or "outline:none" in body:
            assert "box-shadow" in body or "border-color" in body, (
                f"{selector.strip()} removes the ring and draws nothing in its place"
            )


FIXED_WIDTH = re.compile(r"(?<!max-)(?<!min-)width:\s*(\d{3,})px")


def _oversized_fixed_widths(name: str, css: str) -> list[str]:
    """A rule that pins a width at or above a small phone's viewport needs a max-width to go with it,
    or the page scrolls sideways wherever the surface is narrower than the author's window."""
    offenders: list[str] = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = rule.group(1).strip().replace("\n", " "), rule.group(2)
        for match in FIXED_WIDTH.finditer(body):
            if int(match.group(1)) >= 320 and "max-width" not in body:
                offenders.append(f"{name}: {selector[:60]} sets width:{match.group(1)}px with no max-width")
    return offenders


def test_shipped_ui_does_not_pin_itself_wider_than_a_phone() -> None:
    from raven.channels.webchat.channel import INDEX_HTML

    style = re.search(r"<style>(.*?)</style>", INDEX_HTML, re.S)
    assert style is not None, "the fallback page must carry its stylesheet inline"
    sheets = {
        "popup.css": (ROOT / "extension" / "src" / "popup" / "popup.css").read_text(encoding="utf-8"),
        "webchat": style.group(1),
        "spa index.css": (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8"),
    }
    offenders = [hit for name, css in sheets.items() for hit in _oversized_fixed_widths(name, css)]
    assert not offenders, "\n".join(offenders)


def test_the_fixed_width_detector_detects_the_pattern_it_forbids() -> None:
    assert _oversized_fixed_widths("probe", "body { width: 380px; min-height: 500px; }")
    assert not _oversized_fixed_widths("probe", "body { width: 380px; max-width: 100%; }")
    assert not _oversized_fixed_widths("probe", ".chip { min-width: 640px; }")


# A var() with a fallback, read with a balanced scan rather than a regex: the fallback may contain a
# call (rgba()) or another var(), and a pattern that stops at the first ")" reports the rest of the
# declaration as the fallback value.
_VAR_HEAD = re.compile(r"var\(\s*(--dt-[a-zA-Z0-9-]+)\s*,")


def _var_fallbacks(text: str) -> list[tuple[str, str]]:
    """Every (token, fallback) pair on a ``--dt-`` custom property, outermost first."""
    out: list[tuple[str, str]] = []
    pos = 0
    while True:
        match = _VAR_HEAD.search(text, pos)
        if match is None:
            return out
        depth = 0
        end = -1
        for i in range(text.index("(", match.start()), len(text)):
            depth += text[i] == "("
            depth -= text[i] == ")"
            if depth == 0:
                end = i
                break
        assert end != -1, f"unbalanced var() at offset {match.start()}"
        out.append((match.group(1), text[match.end() : end].strip()))
        pos = match.end()


def _theme_values(name: str) -> dict[str, str]:
    data = json.loads((DESIGN / name).read_text(encoding="utf-8"))
    out: dict[str, str] = {}

    def walk(node: Any, prefix: list[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, [*prefix, key])
        elif prefix:
            out["--dt-" + "-".join(prefix)] = str(node)

    for group, values in data.items():
        if group.startswith("$") or group in {"description", "version"}:
            continue
        walk(values, [group])
    return out


def _web_sources() -> list[Path]:
    """Everything the SPA ships, minus the token layer that is allowed to name colours and the sheet
    generated from it."""
    return [
        path
        for path in (WEB / "src").rglob("*")
        if path.suffix in {".css", ".tsx", ".ts"}
        and ".test." not in path.name
        and path.name not in {"themes.css", "tailwind-theme.css"}
        and "design" not in path.parts
    ]


def test_nothing_stands_between_a_component_and_a_published_token() -> None:
    """web/src/styles/themes.css declares every token of all three themes before React mounts, so a
    literal after the comma is a second copy of a value the theme already owns. It can only describe
    one of the three themes, it goes stale the moment the palette moves, and it is what paints for a
    user who picked another accent."""
    published: set[str] = set()
    for theme in THEME_FILES:
        published |= set(_theme_values(theme))
    offenders: list[str] = []
    for path in _web_sources():
        for token, fallback in _var_fallbacks(path.read_text(encoding="utf-8", errors="replace")):
            if token in published:
                offenders.append(f"{path.relative_to(WEB)}: {token} still carries {fallback[:60]!r}")
    assert not offenders, "\n".join(offenders)


def test_the_fallback_scanner_reads_the_nesting_the_rule_has_to_see_through() -> None:
    assert _var_fallbacks("color: var(--dt-colors-accent-muted, rgba(124, 58, 237, 0.5));") == [
        ("--dt-colors-accent-muted", "rgba(124, 58, 237, 0.5)")
    ]
    assert _var_fallbacks("background: var(--dt-colors-surface-card, var(--dt-colors-bg-secondary))") == [
        ("--dt-colors-surface-card", "var(--dt-colors-bg-secondary)")
    ]
    assert _var_fallbacks("box-shadow: 0 0 3px var(--dt-colors-accent-default)") == []


def test_the_generated_sheets_equal_the_token_files_and_are_loaded() -> None:
    """A generated sheet is only trustworthy while the generator still agrees with it, and a sheet the
    SPA never imports paints nothing. Both sheets are compared byte for byte: `themes.css` carries the
    three colour scales and `tailwind-theme.css` carries the radius, type and easing utilities that
    would otherwise stay on Tailwind's own defaults, so a stale one of those paints a stale half."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_theme_css", ROOT / "scripts" / "gen_theme_css.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    index = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    rendered = module.render()
    sheet = WEB / "src" / "styles" / "themes.css"
    assert sheet.read_text(encoding="utf-8") == rendered, "themes.css is stale — run python scripts/gen_theme_css.py"
    assert '@import "./themes.css";' in index
    for selector in (':root,\n[data-theme="dark"]', '[data-theme="light"]', '[data-theme="midnight"]'):
        assert selector in rendered, f"{selector} block missing from the sheet"

    tailwind = module.render_tailwind()
    tailwind_sheet = WEB / "src" / "styles" / "tailwind-theme.css"
    assert tailwind_sheet.read_text(encoding="utf-8") == tailwind, (
        "tailwind-theme.css is stale — run python scripts/gen_theme_css.py"
    )
    assert '@import "./tailwind-theme.css";' in index


def test_token_files_validate_against_their_schema() -> None:
    import jsonschema

    schema = json.loads((DESIGN / "tokens.schema.json").read_text(encoding="utf-8"))
    for theme in THEME_FILES:
        data = json.loads((DESIGN / theme).read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
        assert data["colors"]["chart"], f"{theme} declares no chart series"


def test_shipped_iframes_are_sandboxed_without_a_self_escape() -> None:
    """allow-scripts together with allow-same-origin hands the embedder its own origin back."""
    offenders: list[str] = []
    for path in (WEB / "src").rglob("*.tsx"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for tag in re.findall(r"<iframe\b[^>]*>", text, re.S):
            sandbox = re.search(r'sandbox=\{?"([^"}]*)"?', tag)
            if sandbox is None:
                offenders.append(f"{path.name}: <iframe> without sandbox: {tag[:70]}")
            elif "allow-scripts" in sandbox.group(1) and "allow-same-origin" in sandbox.group(1):
                offenders.append(f"{path.name}: sandbox allows scripts and same-origin together")
    assert not offenders, "\n".join(offenders)


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


def _load_theme_generator() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_theme_css", ROOT / "scripts" / "gen_theme_css.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OFFLINE_SHEETS = {
    "webchat": ROOT / "raven" / "channels" / "webchat" / "channel.py",
    "extension popup": ROOT / "extension" / "src" / "popup" / "popup.css",
    "offline shell": ROOT / "web" / "public" / "offline.html",
    # The webview the editor hosts: a document of this product that loads no bundle, so it is exactly as
    # unable to drift quietly as the other three.
    "VS Code chat panel": ROOT / "extension" / "vscode" / "src" / "panel.ts",
}

#: A sheet's own literals are the ones outside *any* generated region: the token block, and the face
#: block that has to name a `font-family` to do its job at all.
_GENERATED_REGION = re.compile(r"/\* (?:design-tokens|brand-fonts):start.*?:end \*/", re.S)

#: A document that inlines the brand mark carries the vector's own fills. They are not a private palette:
#: `test_a_document_that_inlines_the_mark_inlines_this_one` compares that drawing with `site/favicon.svg`
#: byte for byte, which is a stronger claim than "this hex is in the tokens".
_INLINED_MARK = re.compile(r"<!-- brand-mark:start -->.*?<!-- brand-mark:end -->", re.S)

SHEETS_WITHOUT_THEIR_OWN_COLOUR = {
    **OFFLINE_SHEETS,
    "offline worker": ROOT / "web" / "public" / "sw.js",
}


def _region_of(text: str, generator: Any) -> str:
    start = text.index(generator.SENTINEL_START)
    end = text.index(generator.SENTINEL_END, start) + len(generator.SENTINEL_END)
    return text[start:end]


def _own_text(text: str) -> str:
    """The sheet with every generated region blanked, line count intact so messages still point."""
    blanked = _GENERATED_REGION.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _INLINED_MARK.sub(lambda m: "\n" * m.group(0).count("\n"), blanked)


def _region_bodies(generator: Any) -> dict[str, str]:
    """Each host document with its own generated region cut out, keyed by the command that prints it."""
    bodies: dict[str, str] = {}
    for command, hosts in generator.REGION_HOSTS.items():
        start, end = generator._surface_sentinels(command)
        for rel in hosts:
            _, marker, tail = (ROOT / rel).read_text(encoding="utf-8", errors="replace").partition(start)
            assert marker, f"{rel} is registered as a {command} host and holds no region"
            _, _, after = tail.partition(end)
            bodies[command] = bodies.get(command, "") + after
    return bodies


def test_the_region_carries_no_token_the_surfaces_never_read() -> None:
    """The region is shared, which makes it easy to keep a declaration after the rule that read it is
    gone -- and an alias no rule reads is a colour someone will later assume is live. The list of what
    belongs is therefore measured off the host documents, not typed next to the generator."""
    gen = _load_theme_generator()
    bodies = _region_bodies(gen)
    declared = set(gen.SURFACE_TOKENS)
    scaffold_declared = {name for name in declared if "font-family" not in name}

    for command, allowed in (("--print-surface", declared), ("--print-scaffold", scaffold_declared)):
        referenced = set(re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", bodies[command]))
        dangling = sorted(referenced - allowed)
        assert not dangling, f"a {command} host reads tokens its region does not declare: {dangling}"

    unread = sorted(declared - set(re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", bodies["--print-surface"])))
    assert not unread, f"the shared region declares tokens no surface reads any more: {unread}"


def test_the_region_reader_notices_a_declaration_no_rule_reads() -> None:
    """The premise of the guard above: a token has to stop counting as read when the rules stop reading
    it, or the unused list is a list of nothing and the gate passes on whatever the tree holds."""
    gen = _load_theme_generator()
    surface = _region_bodies(gen)["--print-surface"]
    declared = set(gen.SURFACE_TOKENS)

    def read(text: str) -> set[str]:
        return set(re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", text))

    assert read(surface) <= declared, "a shipped host already reads more than the region declares"
    dropped = re.sub(r"var\(\s*--dt-colors-border-focus\s*[,)][^;]*[;)]?", "", surface)
    assert "--dt-colors-border-focus" not in read(dropped), "the reader kept a token nothing asks for"
    assert sorted(declared - read(dropped)) == ["--dt-colors-border-focus"], sorted(declared - read(dropped))


@pytest.mark.parametrize("label", sorted(OFFLINE_SHEETS))
def test_offline_surfaces_embed_the_generated_token_region(label: str) -> None:
    """Every sheet below is a document that never loads the SPA bundle, so each one hand-copied a
    palette until a generator printed it. The copies drifted: the webchat page invented #8b5cf6 as its
    button surface and put white on it at 4.23:1, and the editor's panel kept a navy of its own while
    the site painted violet.
    The region between the sentinels is generated output, checked byte for byte, and every token the
    sheet references has to be declared inside it."""
    generator = _load_theme_generator()
    text = OFFLINE_SHEETS[label].read_text(encoding="utf-8", errors="replace")
    region = _region_of(text, generator)
    assert region == generator.surface_block(), f"{label}: embedded region is not what the generator emits"

    declared = set(re.findall(r"^\s*(--dt-[a-zA-Z0-9-]+):", region, re.M))
    body = re.sub(
        r"\s*" + re.escape(generator.SENTINEL_START) + r".*" + re.escape(generator.SENTINEL_END), "", text, flags=re.S
    )
    referenced = set(re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", body))
    dangling = sorted(referenced - declared)
    assert not dangling, f"{label} references tokens its region does not declare: {dangling}"

    # the sheet's own short names are part of the contract too: an alias no rule reads is a colour
    # someone will later assume is live
    aliases = re.findall(r"^\s{2}(--(?!dt-)[a-z-]+):", body, re.M)
    used = set(re.findall(r"var\(\s*(--[a-z-]+)", body))
    unused = sorted(name for name in aliases if name not in used)
    assert not unused, f"{label} declares aliases nothing uses: {unused}"


@pytest.mark.parametrize("label", sorted(SHEETS_WITHOUT_THEIR_OWN_COLOUR))
def test_offline_surfaces_carry_no_colour_of_their_own(label: str) -> None:
    """Outside the generated region these sheets may not name a colour: that is how the private
    palette got written in the first place."""
    text = SHEETS_WITHOUT_THEIR_OWN_COLOUR[label].read_text(encoding="utf-8", errors="replace")
    body = _own_text(text)
    offenders = [
        f"{label}:{i}: {hit}" for i, line in enumerate(body.splitlines(), 1) for hit in _COLOUR_LITERAL.findall(line)
    ]
    assert not offenders, "\n".join(offenders)


# `em` sizes are deliberately absent: `.bubble code` at .8em scales with the message it sits in, which
# is what a relative unit is for. Absolute lengths and font stacks are the part that must come from the
# embedded region, because nothing else on those pages can be retuned by a theme.
_OFFLINE_TYPE_LITERAL = re.compile(
    r"(font-size:\s*[0-9.]+(?:px|rem)\b)|(font:\s*[0-9.]+px)|(font-family:(?!\s*var\()[^;]+)"
)


@pytest.mark.parametrize("label", sorted(OFFLINE_SHEETS))
def test_the_offline_surfaces_take_their_corners_and_type_from_the_region(label: str) -> None:
    """The same argument the colour guard makes, for the numbers that were left behind.

    Both sheets used to carry their own corners (`.9rem`, `12px 12px 4px 12px`, `.35rem`) and their own
    type (`font: 14px/1.55 system-ui`), so the gateway chat page rendered the product's strings in the
    operating system's font while the SPA rendered them in IBM Plex Sans. The region is now the only
    place either sheet may get a length or a family from."""
    text = OFFLINE_SHEETS[label].read_text(encoding="utf-8", errors="replace")
    body = _own_text(text)
    offenders = [f"{label}: border-radius: {hit}" for hit in _off_scale_corners(body)]
    offenders += [
        f"{label}:{i}: {hit.group(0).strip()}"
        for i, line in enumerate(body.splitlines(), 1)
        if (hit := _OFFLINE_TYPE_LITERAL.search(line))
    ]
    offenders += [
        f"{label}: {token} still carries the literal fallback {fallback!r}" for token, fallback in _var_fallbacks(body)
    ]
    assert not offenders, "\n".join(offenders)


def test_the_offline_type_reader_flags_a_stack_and_not_a_token() -> None:
    r"""The lookahead has to sit before the whitespace: `\s*(?!var\()` backtracks to zero spaces and
    reports `font-family: var(--dt-…)`, which is the one thing the rule exists to allow."""
    assert _OFFLINE_TYPE_LITERAL.search("body { font: 14px/1.5 system-ui, sans-serif; }")
    assert _OFFLINE_TYPE_LITERAL.search("code { font-family: ui-monospace, monospace; }")
    assert _OFFLINE_TYPE_LITERAL.search("h1 { font-size: 0.9rem; }")
    assert not _OFFLINE_TYPE_LITERAL.search("code { font-size: .85em; }")
    assert not _OFFLINE_TYPE_LITERAL.search("body { font-family: var(--dt-typography-font-family-sans); }")
    assert not _OFFLINE_TYPE_LITERAL.search("button { font: inherit; }")


# The storefront's devices, and the surfaces that are expected to paint them. A device is identified by the
# rule that publishes it in the sheet plus the declarations that make it, and the recipe is read out of
# web/src/styles/index.css at test time rather than retyped here -- this file cannot be the place a device
# quietly changes meaning.
DEVICE_RULES = {
    "glass card": ((".card", "background-image"),),
    "inset light": ((".card, .card-bordered, .stat-card", "box-shadow"),),
    "pointer light": (
        (".card::before, .card-bordered::before, .stat-card::before", "background"),
        (".card::before, .card-bordered::before, .stat-card::before", "transition"),
    ),
    "translucent chrome": ((".shell-aside", "background-color"), (".shell-aside", "backdrop-filter")),
    "grain": (
        ("body::after", "background-image"),
        ("body::after", "opacity"),
        ("body::after", "background-size"),
    ),
    "lit headline": (
        (".page-title", "background-image"),
        (".page-title", "background-size"),
        (".page-title", "animation"),
    ),
    "primary action": (
        (".btn-primary", "background-image"),
        (".btn-primary", "transition"),
        (".btn-primary:hover", "filter"),
        (".btn-primary:hover", "box-shadow"),
        (".btn-primary:active", "transform"),
    ),
    "kicker": (
        (".nav-section-label", "letter-spacing"),
        (".nav-section-label", "color"),
        (".nav-section-label::before", "width"),
        (".nav-section-label::before", "background"),
    ),
    "card wash": ((".card-wash", "background-image"),),
}

#: What each surface of this product is expected to carry, and why the rest of the vocabulary is absent
#: from it. A device with no reason and no recipe in the surface is a gap this gate reports.
DEVICE_SURFACES: dict[str, tuple[Path, dict[str, str]]] = {
    "VS Code chat panel": (
        ROOT / "extension" / "vscode" / "src" / "panel.ts",
        {
            "glass card": "",
            "inset light": "",
            "pointer light": "",
            "translucent chrome": "",
            "grain": "",
            "lit headline": "",
            "primary action": "",
            "kicker": "the panel has no labelled sections to announce: a header, a log, a composer",
            "card wash": "the replies are the lit surface, as on every other chat here",
        },
    ),
    "extension popup": (
        ROOT / "extension" / "src" / "popup" / "popup.css",
        {
            "glass card": "",
            "inset light": "",
            "pointer light": "",
            "translucent chrome": "",
            "grain": "",
            "lit headline": "",
            "primary action": "",
            "kicker": "",
            "card wash": "the popup is a column of replies, the same reason the gateway page has none",
        },
    ),
    "gateway chat page": (
        ROOT / "raven" / "channels" / "webchat" / "channel.py",
        {
            "glass card": "",
            "inset light": "",
            "pointer light": "",
            "translucent chrome": "",
            "grain": "",
            "lit headline": "",
            "primary action": "",
            "kicker": "",
            "card wash": "the reply bubbles are the lit surface here and they answer the cursor; a wash "
            "sized to a card nobody hovers is the flatter thing",
        },
    ),
    "generated starter": (
        ROOT / "raven" / "core" / "scaffold_api.py",
        {
            "glass card": "",
            "inset light": "",
            "pointer light": "a starter ships no pointer wiring, and a light that never moves is the static "
            "wash, which the starter does carry",
            "translucent chrome": "the starter is one centred card, not a shell with bars",
            "grain": "",
            "lit headline": "",
            "primary action": "",
            "kicker": "",
            "card wash": "",
        },
    ),
    "offline shell": (
        ROOT / "web" / "public" / "offline.html",
        {
            "glass card": "",
            "inset light": "",
            "pointer light": "the page a reader reaches when the bundle cannot load has one card and no "
            "cursor work to reward; the static wash is the device that reaches it",
            "translucent chrome": "there is no bar over content: the shell is a single centred card",
            "grain": "",
            "lit headline": "",
            "primary action": "",
            "kicker": "",
            "card wash": "",
        },
    ),
}


def _canon(text: str) -> str:
    """Whitespace collapsed, and the spaces a wrapped value hangs off its parentheses removed: the sheet
    breaks the card ramp over five lines and every host writes it on one, and that layout is not drift."""
    text = " ".join(text.split())
    text = re.sub(r"\(\s+", "(", text)
    return re.sub(r"\s+\)", ")", text)


def _sheet_blocks(css: str) -> dict[str, dict[str, str]]:
    """`selector -> declaration -> value` for every flat rule in a sheet. Comments go first because they
    sit between rules and would otherwise be read as part of the selector; at-rules go next, because a
    reduce block's paraphrase is not the device and letting it answer here would put the exception in
    charge of the default."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@[a-z-]+[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", css)
    blocks: dict[str, dict[str, str]] = {}
    for raw_selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(raw_selector.split())
        if not selector or selector.startswith("@"):
            continue
        declarations = blocks.setdefault(selector, {})
        for declaration in body.split(";"):
            prop, sep, value = declaration.partition(":")
            if sep:
                declarations[" ".join(prop.split()).lower()] = " ".join(value.split())
    return blocks


def _device_recipes(css: str) -> dict[str, list[str]]:
    """The exact declarations the sheet publishes for each device, as `property: value`."""
    blocks = _sheet_blocks(css)
    recipes: dict[str, list[str]] = {}
    for device, wanted in DEVICE_RULES.items():
        lines = []
        for selector, prop in wanted:
            assert selector in blocks, f"the sheet no longer publishes {selector}, the rule {device} is made of"
            assert prop in blocks[selector], f"{selector} no longer declares {prop}, which {device} is made of"
            lines.append(_canon(f"{prop}: {blocks[selector][prop]}"))
        recipes[device] = lines
    return recipes


def _sheet_css() -> str:
    return (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("label", sorted(DEVICE_SURFACES))
def test_a_surface_paints_the_storefront_devices_it_is_expected_to_carry(label: str) -> None:
    """A paraphrase is how these surfaces drifted before: the gateway page invented its own bubble ramp and
    the popup pulled its chrome from a CDN it was never allowed to reach, and each one still read as "glass"
    to whoever wrote it. So the recipe is matched as the sheet writes it -- byte for byte after whitespace --
    and a surface has to say why it carries less than the storefront does."""
    path, expected = DEVICE_SURFACES[label]
    flat = _canon(_own_text(path.read_text(encoding="utf-8", errors="replace")))
    recipes = _device_recipes(_sheet_css())

    offenders = []
    for device, reason in expected.items():
        absent = [line for line in recipes[device] if line not in flat]
        if reason:
            # The excuse has to stay true: a surface that quietly starts carrying the device it claims to
            # skip is the same drift in the other direction, with a comment now lying about it.
            if not absent:
                offenders.append(f"{label} claims it carries no {device}, and the recipe is there: {reason}")
            continue
        if absent:
            offenders.append(f"{label} does not paint {device}: {absent}")
    assert not offenders, "\n".join(offenders)


def test_the_device_reader_notices_a_paraphrased_recipe() -> None:
    """A gate that only ever sees the shipped strings proves nothing about its own reading. Re-tuning the
    glass card's mix is the change that used to pass: the surface stayed "glass" and drifted two points of
    transparency away from the storefront."""
    recipe = _device_recipes(_sheet_css())["glass card"]
    assert len(recipe) == 1, "the glass card is one declaration; the paraphrase below assumes so"
    shipped = _canon(_own_text(DEVICE_SURFACES["gateway chat page"][0].read_text(encoding="utf-8", errors="replace")))
    assert recipe[0] in shipped, "the premise is gone: the gateway page no longer carries this recipe"

    paraphrased = shipped.replace("surface-card) 88%", "surface-card) 90%", 1)
    assert recipe[0] not in paraphrased, "a re-tuned ramp still counted as the sheet's own"


def test_the_device_recipes_move_when_the_sheet_moves() -> None:
    """Were the recipe a string typed next to the test, editing the sheet would not move the guard and the
    two would drift apart in silence. Paraphrase the sheet in memory and the device it publishes changes."""
    css = _sheet_css()
    shipped = _device_recipes(css)["lit headline"]
    edited = css.replace(
        "linear-gradient(110deg, var(--dt-colors-text-primary) 35%",
        "linear-gradient(110deg, var(--dt-colors-text-primary) 30%",
        1,
    )
    assert edited != css, "the headline ramp this gate reads is not the one the sheet publishes"
    assert _device_recipes(edited)["lit headline"] != shipped


def test_shipped_chat_pages_declare_their_colour_contrast() -> None:
    """Both pages are plain CSS, so their pairs are computed from the tokens they now embed rather
    than from hexes typed into this file -- a copy of a colour here would assert nothing about the
    product."""
    dark = _theme_values("tokens.json")
    token = lambda name: dark[f"--dt-colors-{name}"]  # noqa: E731

    page = token("bg-primary")
    surface = token("bg-secondary")
    accent = token("accent-default")
    bubble = _as_paint(to_rgba(accent, 0.26), surface)
    notice = _as_paint(to_rgba(accent, 0.14), surface)

    pairs = (
        ("body text on the page", token("text-primary"), page, NORMAL_TEXT),
        ("body text on a panel", token("text-primary"), surface, NORMAL_TEXT),
        ("muted text on the page", token("text-secondary"), page, NORMAL_TEXT),
        ("muted text on a panel", token("text-secondary"), surface, NORMAL_TEXT),
        ("link on a panel", token("text-link"), surface, NORMAL_TEXT),
        ("button label on the accent", token("text-on-accent"), accent, NORMAL_TEXT),
        ("user bubble text", token("text-primary"), bubble, NORMAL_TEXT),
        ("user bubble link", token("text-primary"), bubble, NORMAL_TEXT),
        ("notice bar text", token("text-primary"), notice, NORMAL_TEXT),
        ("live status dot", token("status-success"), page, LARGE_TEXT_OR_UI),
        ("down status dot", token("status-error"), page, LARGE_TEXT_OR_UI),
        ("focus border on a panel", token("border-focus"), surface, LARGE_TEXT_OR_UI),
        # The editor's panel carries its connection state in a pill and its composer in a real button,
        # so those are the pairs a reader of that surface actually looks at.
        ("connected pill", token("status-success"), _as_paint(token("status-success-bg"), surface), NORMAL_TEXT),
        ("waiting pill", token("status-warning"), _as_paint(token("status-warning-bg"), surface), NORMAL_TEXT),
        ("disconnected pill", token("status-error"), _as_paint(token("status-error-bg"), surface), NORMAL_TEXT),
        ("label on a hovered accent", token("text-on-accent"), token("accent-hover"), NORMAL_TEXT),
        ("label on a pressed accent", token("text-on-accent"), token("accent-active"), NORMAL_TEXT),
        ("muted placeholder on a well", token("text-secondary"), page, NORMAL_TEXT),
    )
    for label, foreground, background, minimum in pairs:
        ratio = contrast(foreground, background)
        assert ratio >= minimum, f"{label}: {foreground} on {background} = {ratio:.2f}:1, need {minimum}"


def _jsx_tags(name: str) -> list[tuple[str, int, str]]:
    """Every `<name ...>` tag in the SPA sources, with the file and line it starts on."""
    out: list[tuple[str, int, str]] = []
    for path in _web_sources():
        if path.suffix != ".tsx":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(rf"<{name}\b", text):
            braces = 0
            index = match.start()
            while index < len(text):
                char = text[index]
                if char == "{":
                    braces += 1
                elif char == "}":
                    braces -= 1
                elif char == ">" and braces == 0:
                    break
                index += 1
            out.append(
                (str(path.relative_to(WEB)), text[: match.start()].count(chr(10)) + 1, text[match.start() : index + 1])
            )
    return out


def test_no_chart_axis_falls_back_to_the_library_default_colour() -> None:
    """recharts paints an unstyled axis with #666: 2.72:1 on the dark card and 3.35:1 on midnight, on
    tick labels that are 9-11px -- text a user has to read. Every axis therefore names a token, and the
    token has to clear the text minimum against the panel the chart sits on."""
    offenders: list[str] = []
    for name in ("XAxis", "YAxis"):
        for file, line, tag in _jsx_tags(name):
            stroke = re.search(r'stroke=\{?"var\((--dt-[a-zA-Z0-9-]+)\)', tag)
            if stroke is None:
                offenders.append(f"{file}:{line}: <{name}> has no token stroke -> {tag[:70]}")
                continue
            token = stroke.group(1)
            for theme in THEME_FILES:
                values = _theme_values(theme)
                value = values.get(token)
                if value is None:
                    offenders.append(f"{file}:{line}: {token} is not published by {theme}")
                    continue
                card = values["--dt-colors-surface-card"]
                ratio = contrast(value, card)
                if ratio < NORMAL_TEXT:
                    offenders.append(f"{file}:{line}: <{name}> {token}={value} on {theme} card = {ratio:.2f}:1")
    assert not offenders, "\n".join(offenders)


def _tooltip_box_offenders(tags: list[tuple[str, int, str]]) -> list[str]:
    """Tooltip tags that paint their box outside the sheet. The library's default panel is a white card with
    black text and answers to no theme; a page-supplied `contentStyle` answers to the theme only through token
    names written into a JS object, which no rule reads back and no theme can restyle."""
    offenders: list[str] = []
    for file, line, tag in tags:
        if "contentStyle" in tag:
            offenders.append(f"{file}:{line}: <Tooltip> paints its own box: contentStyle")
        elif "content={<ChartTooltip" not in tag:
            offenders.append(f"{file}:{line}: <Tooltip> left to the library's default box")
    return offenders


def test_no_tooltip_is_left_to_the_library_default_box() -> None:
    offenders = _tooltip_box_offenders(_jsx_tags("Tooltip"))
    assert not offenders, "\n".join(offenders)


def test_the_tooltip_reader_notices_a_box_painted_outside_the_sheet() -> None:
    assert _tooltip_box_offenders(
        [("p.tsx", 1, '<Tooltip contentStyle={{ backgroundColor: "var(--dt-colors-bg-secondary)" }} />')]
    ) == ["p.tsx:1: <Tooltip> paints its own box: contentStyle"]
    assert _tooltip_box_offenders([("p.tsx", 2, "<Tooltip />")]) == [
        "p.tsx:2: <Tooltip> left to the library's default box"
    ]
    assert _tooltip_box_offenders([("p.tsx", 3, "<Tooltip content={<ChartTooltip />} />")]) == []


def _css_rules(css: str) -> list[tuple[str, str]]:
    """Every (selector, body) pair, descending into at-rule blocks so a rule that only exists inside
    a `@media` query is still read."""
    out: list[tuple[str, str]] = []
    position = 0
    while True:
        brace = css.find("{", position)
        if brace == -1:
            return out
        end = _skip_block(css, brace)
        selector = css[position:brace].strip().replace("\n", " ")
        body = css[brace + 1 : end - 1]
        if selector.startswith("@"):
            out.extend(_css_rules(body))
        elif selector:
            out.append((selector, body))
        position = end


_LANDING_PANELS = ("--bg", "--bg-panel", "--bg-card", "--bg-raised")
_GRADIENT_STOP = re.compile(r"var\(--[a-z-]+\)|#[0-9a-fA-F]{3,6}|rgba?\([^)]*\)")


def _landing_variables(css: str) -> dict[str, str]:
    root = next((body for selector, body in _css_rules(css) if selector == ":root"), "")
    return dict(re.findall(r"(--[a-z-]+):\s*([^;]+);", root))


def _resolve_colour(text: str, variables: dict[str, str]) -> tuple[float, float, float, float] | None:
    """A CSS colour as channels plus alpha, following one var() level; None when it is not a colour."""
    value = text.strip()
    for _ in range(2):
        match = re.fullmatch(r"var\((--[a-z-]+)\)", value)
        if match is None:
            break
        value = variables.get(match.group(1), "").strip()
    if value.startswith("#"):
        body = value[1:]
        if len(body) == 3:
            body = "".join(ch * 2 for ch in body)
        if len(body) != 6:
            return None
        channels = [int(body[i : i + 2], 16) for i in (0, 2, 4)]
        return (float(channels[0]), float(channels[1]), float(channels[2]), 1.0)
    if value.startswith(("rgb(", "rgba")):
        parts = [float(p) for p in re.split(r"[,\s/]+", value[value.index("(") + 1 : value.rindex(")")].strip()) if p]
        if len(parts) < 3:
            return None
        alpha = parts[3] if len(parts) > 3 else 1.0
        return (parts[0], parts[1], parts[2], alpha)
    return None


def _over(
    foreground: tuple[float, float, float, float], background: tuple[float, float, float]
) -> tuple[float, float, float]:
    if foreground[3] >= 1.0:
        return foreground[:3]
    alpha = foreground[3]
    return tuple(foreground[i] * alpha + background[i] * (1 - alpha) for i in range(3))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(c))) for c in rgb])


def test_landing_labels_are_readable_on_every_panel_they_paint_on() -> None:
    """The storefront is the surface a buyer reads first. It now shares one scale with the SPA --
    `test_site_app_parity.py` holds the two files to the same values -- but value equality says nothing
    about which colour a storefront rule actually puts on which, so this measures the declarations
    themselves. Every rule that declares a label and a background is read: a translucent surface is
    composited over each dark panel it could sit on and the worst answer is the one kept, because the
    rule does not say which ancestor it lands on. This is what found white on --violet at 4.23:1 in
    ::selection and in the primary button's gradient stop."""
    css = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    variables = _landing_variables(css)
    panels = []
    for name in _LANDING_PANELS:
        resolved = _resolve_colour(name if name.startswith("var") else f"var({name})", variables)
        assert resolved is not None, f"site/styles.css declares no readable {name}"
        panels.append(resolved[:3])

    offenders: list[str] = []
    for selector, body in _css_rules(css):
        label = re.search(r"(?<![\w-])color:\s*([^;]+);", body)
        surface = re.search(r"background(?:-image)?:\s*([^;]+);", body)
        if label is None or surface is None:
            continue
        ink = _resolve_colour(label.group(1), variables)
        if ink is None:
            continue
        declaration = surface.group(1)
        stops = _GRADIENT_STOP.findall(declaration) if "gradient" in declaration else [declaration]
        for background in panels:
            paints = [
                _over(step, background)
                for step in (_resolve_colour(stop, variables) for stop in (stops or [declaration]))
                if step is not None
            ] or [background]
            worst = min(contrast(_hex(_over(ink, paint)), _hex(paint)) for paint in paints)
            if worst < NORMAL_TEXT:
                offenders.append(
                    f"{selector[:52]}: {label.group(1).strip()} on {declaration.strip()[:40]} = {worst:.2f}:1"
                )
    assert not offenders, "\n".join(offenders)


def test_the_landing_reads_only_its_declared_scale() -> None:
    """A colour the landing invents is invisible to the gate above's token names and to a brand change:
    outside the :root block the stylesheet may only reference its own variables."""
    css = (ROOT / "site" / "styles.css").read_text(encoding="utf-8")
    offenders = []
    for selector, body in _css_rules(css):
        if selector == ":root":
            continue
        for match in _COLOUR_LITERAL.finditer(body):
            offenders.append(f"{selector[:48]}: {match.group(0)}")
    assert not offenders, "\n".join(offenders)


_COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|\brgba?\([^)]*\)")

# Tailwind's own palette: usable, but a colour the themes do not own, so it survives neither a theme
# switch nor the contrast gates above.
_PALETTE_CLASS = re.compile(
    r"\b(?:bg|text|border|ring|fill|stroke|from|to|via)-(?:red|rose|pink|fuchsia|purple|violet|"
    r"indigo|blue|sky|cyan|teal|emerald|green|lime|yellow|amber|orange|gray|grey|slate|zinc|stone|"
    r"neutral)-\d{2,3}\b"
)


def test_markdown_surfaces_restore_what_preflight_took_away() -> None:
    """react-markdown emits h1-h6, ul/ol and a, and Tailwind's preflight resets each of them --
    headings to `font-size: inherit`, lists to `list-style: none`, anchors to `color: inherit;
    text-decoration: inherit` -- so a chat answer arrived with no structure and no visible links.
    `.prose` has to put every one of them back, and the link cue cannot be colour alone."""
    css = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    # index by each selector in the list, so `.prose ul ul` cannot stand in for `.prose ul`
    declarations: dict[str, str] = {}
    for selector, body in _css_rules(css):
        for part in selector.split(","):
            name = part.strip()
            if name.startswith(".prose"):
                declarations[name] = f"{declarations.get(name, '')} {body}"

    def declared(selector: str) -> str:
        return re.sub(r"\s+", " ", declarations.get(selector, ""))

    offenders: list[str] = []

    # every heading level react-markdown can emit, and both list kinds, have to be re-declared on
    # their own selector: preflight flattened them in one rule, so a near-miss is not evidence
    for level in ("h1", "h2", "h3"):
        if "font-size" not in declared(f".prose {level}"):
            offenders.append(f".prose {level} declares no font-size: preflight left it at inherit")
    for kind in ("ul", "ol"):
        if "list-style" not in declared(f".prose {kind}"):
            offenders.append(f".prose {kind} declares no list-style: preflight set ol,ul,menu to none")

    anchor = declared(".prose a")
    if not anchor:
        offenders.append(".prose has no link rule at all")
    else:
        if "text-decoration: underline" not in anchor:
            offenders.append(".prose a carries no text-decoration: underline -- colour alone is not a cue")
        link = re.search(r"color:\s*var\((--dt-[a-zA-Z0-9-]+)\)", anchor)
        if link is None:
            offenders.append(".prose a does not take its colour from a token")
        else:
            token = link.group(1)
            for theme in THEME_FILES:
                values = _theme_values(theme)
                if token not in values:
                    offenders.append(f"{theme} publishes no {token}")
                    continue
                card = values["--dt-colors-surface-card"]
                ratio = contrast(values[token], card)
                if ratio < NORMAL_TEXT:
                    offenders.append(f"{theme}: .prose link {values[token]} on the card = {ratio:.2f}:1")
    assert not offenders, "\n".join(offenders)


def test_theme_differences_come_from_tokens_not_from_class_remaps() -> None:
    """`[data-theme="light"] .bg-gray-900 { ... }` was how the SPA used to do themes: a parallel list of
    Tailwind utilities with token values pasted behind them. Fifteen such rules outlived the classes
    they remapped, and the pattern itself is what stops a palette being a system -- the theme lives in
    the tokens, and a per-theme utility remap is a second copy that drifts."""
    css = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    offenders = [
        selector.strip()[:70]
        for selector, _ in _css_rules(css)
        if re.search(r'\[data-theme="(light|midnight)"\]\s*\.', selector)
    ]
    assert not offenders, "per-theme class remaps found: " + "; ".join(offenders)


MINIMUM_FONT_PX = 10.0
_FONT_PX = re.compile(
    r"text-\[(\d+(?:\.\d+)?)px\]|font-size:\s*(\d+(?:\.\d+)?)px|fontSize=\{(\d+(?:\.\d+)?)\}|fontSize:\s*(\d+(?:\.\d+)?)\}"
)


def test_nothing_renders_text_below_the_floor() -> None:
    """Chart ticks were painted at 9px and micro-labels at 8px. WCAG sets no absolute floor, but the
    product ships at 360px, and a 9px timestamp on a phone is decoration rather than information. Ten
    CSS pixels is the declared floor -- the token scale itself starts at 0.75rem (12px), so anything
    below ten is an arbitrary utility that walked past the scale."""
    offenders: list[str] = []
    for path in _web_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in _FONT_PX.finditer(line):
                size = float(next(group for group in match.groups() if group))
                if size < MINIMUM_FONT_PX:
                    offenders.append(f"{path.relative_to(WEB)}:{lineno}: {size}px")

    for theme in THEME_FILES:
        for name, value in _theme_values(theme).items():
            if not name.startswith("--dt-typography-font-size-") or not value.endswith("rem"):
                continue
            pixels = float(value[:-3]) * 16
            if pixels < MINIMUM_FONT_PX:
                offenders.append(f"{theme}: {name} = {pixels:.1f}px")
    assert not offenders, "\n".join(offenders)


def test_no_component_paints_a_colour_the_theme_does_not_publish() -> None:
    """A literal is a colour no theme owns: invisible to every contrast gate here, unmoved by the
    accent picker, and measured wrong in two of the three themes. web/src/design is where colours are
    allowed to be named, and nowhere else."""
    offenders: list[str] = []
    for path in _web_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for hit in _COLOUR_LITERAL.findall(line):
                offenders.append(f"{path.relative_to(WEB)}:{lineno}: {hit}")
    assert not offenders, "\n".join(offenders)


def test_the_literal_detector_detects_the_pattern_it_forbids() -> None:
    assert _COLOUR_LITERAL.search('style={{ color: "#fff" }}')
    assert _COLOUR_LITERAL.search("backgroundColor: rgba(239, 68, 68, 0.12)")
    assert not _COLOUR_LITERAL.search('color: "var(--dt-colors-text-on-accent)"')
    assert _PALETTE_CLASS.search('className="hover:text-red-400"')
    assert not _PALETTE_CLASS.search('className="text-danger"')


def test_no_component_reaches_past_the_theme_for_a_colour() -> None:
    offenders: list[str] = []
    for path in _web_sources():
        if path.suffix != ".tsx":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for hit in _PALETTE_CLASS.finditer(line):
                offenders.append(f"{path.relative_to(WEB)}:{lineno}: {hit.group(0)}")
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("theme", THEME_FILES)
def test_the_categorical_scale_is_readable_on_the_panel_it_is_drawn_on(theme: str) -> None:
    """Fifteen named hues, shared by the knowledge graph (a canvas, so no gate but this one sees it)
    and the plugin tags. Each is a fill -- a UI part at 3:1 -- and every one of them also clears the text
    minimum of 4.5:1 against the panel it is drawn on, so a hue never has to be lightened to be read."""
    colors = _palette(theme)
    card = colors["surface"]["card"]
    category = colors["category"]
    assert set(category) == {
        "blue",
        "green",
        "amber",
        "violet",
        "pink",
        "cyan",
        "orange",
        "teal",
        "yellow",
        "purple",
        "indigo",
        "red",
        "lime",
        "slate",
        "grey",
    }, f"{theme}: the categorical scale is not the fifteen named hues"
    for name, value in category.items():
        ratio = contrast(value, card)
        assert ratio >= NORMAL_TEXT, f"{theme}: category.{name} {value} on surface.card = {ratio:.2f} < 4.5"
    assert len(set(category.values())) == len(category), f"{theme}: duplicate categorical colours"
    hues = [_hsl(value)[0] for value in category.values()]
    assert max(hues) - min(hues) >= 120, f"{theme}: the categorical hues do not span the wheel"

    # Six of the fifteen hues fill a tag in the console, and each of those publishes the label it carries as
    # text.on-category-*, measured above. The rest are drawn by the knowledge graph, where a node's label is the
    # theme's own ink beside the node rather than on it -- kept to the same minimum, because a hue that reads as
    # a fill today is a hue a tag could be given tomorrow.
    light_label = colors["bg"]["inverse"]
    dark_label = colors["text"]["inverse"]
    for name, value in category.items():
        best = max(contrast(light_label, value), contrast(dark_label, value))
        assert best >= NORMAL_TEXT, f"{theme}: no label clears AA on category.{name} {value} (best {best:.2f}:1)"


def _top_level_blocks(css: str) -> list[tuple[str, str]]:
    """Every ``(selector, body)`` rule outside any @-block, brace-matched from the top level."""
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(css):
        if css[index] == "@":
            end = _skip_block(css, index)
            index = end
            continue
        brace = css.find("{", index)
        if brace == -1:
            break
        end = _skip_block(css, brace)
        selector = css[index:brace].strip()
        if selector and not selector.startswith("}"):
            blocks.append((selector, css[brace + 1 : end - 1]))
        index = end
    return blocks


def _skip_block(css: str, start: int) -> int:
    """Index just past the ``{...}`` group that begins at or after ``start``."""
    open_brace = css.index("{", start)
    depth = 0
    for index in range(open_brace, len(css)):
        depth += css[index] == "{"
        depth -= css[index] == "}"
        if depth == 0:
            return index + 1
    raise AssertionError(f"unbalanced brace from {start}")


def _as_paint(value: str, background: str) -> str:
    """Composite an rgba() token over the surface it is drawn on; hexes pass through."""
    if not value.startswith("rgba"):
        return value
    inner = value[value.index("(") + 1 : -1]
    red, green, blue, alpha = (float(part) for part in inner.split(","))
    back = _to_rgb(background)
    mixed = tuple(
        round(colour * alpha + other * (1 - alpha)) for colour, other in zip((red, green, blue), back, strict=True)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def to_rgba(hex_value: str, alpha: float) -> str:
    """The rgba() form of a hex token, the way `color-mix()` composites it over a surface."""
    red, green, blue = _to_rgb(hex_value)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _to_rgb(hex_value: str) -> tuple[int, ...]:
    body = hex_value.lstrip("#")
    return tuple(int(body[i : i + 2], 16) for i in (0, 2, 4))


_STATE_PATTERNS = (":hover", ":focus-within", ":focus-visible", ":focus")
_STATE_BORDER = re.compile(r"border-color:\s*var\((--dt-[a-zA-Z0-9-]+)\)")
_STATE_RING = re.compile(r"box-shadow:[^;]*?0 0 0 \d+(?:\.\d+)?px var\((--dt-[a-zA-Z0-9-]+)\)")


def test_a_state_indicator_is_perceptible_on_the_panel_it_changes() -> None:
    """A hover border or focus ring painted from a 0.15-alpha wash measures 1.13:1 against the card:
    the state changes and nobody can see it. WCAG counts a state indicator as content, so the token it
    uses has to clear 3:1 against the surface the control is drawn on, in every theme."""
    css = (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    published = {name: _theme_values(name) for name in THEME_FILES}
    offenders: list[str] = []
    for selector, body in _top_level_blocks(css):
        if not any(pattern in selector for pattern in _STATE_PATTERNS):
            continue
        tokens = _STATE_BORDER.findall(body) + _STATE_RING.findall(body)
        for token in tokens:
            for theme, values in published.items():
                value = values.get(token)
                if value is None:
                    offenders.append(f"{selector}: {token} is not published by {theme}")
                    continue
                card = published[theme]["--dt-colors-surface-card"]
                ratio = contrast(_as_paint(value, card), card)
                if ratio < LARGE_TEXT_OR_UI:
                    offenders.append(f"{selector.strip()[:48]}: {token}={value} on {theme} card {card} = {ratio:.2f}:1")
    assert not offenders, "\n".join(offenders)


def test_the_state_indicator_detector_reads_the_declarations_it_forbids() -> None:
    css = ".card:hover {\n  border-color: var(--dt-colors-accent-muted);\n  box-shadow: 0 0 0 3px var(--dt-colors-accent-subtle);\n}"
    blocks = _top_level_blocks(css)
    assert len(blocks) == 1 and ":hover" in blocks[0][0]
    body = blocks[0][1]
    assert _STATE_BORDER.findall(body) == ["--dt-colors-accent-muted"]
    assert _STATE_RING.findall(body) == ["--dt-colors-accent-subtle"]
    assert _as_paint("rgba(124, 58, 237, 0.15)", "#1e2140") == "#2c255a"
    assert _as_paint("rgba(124, 58, 237, 0)", "#1e2140") == "#1e2140"
    assert contrast(_as_paint("rgba(124, 58, 237, 0.15)", "#1e2140"), "#1e2140") < LARGE_TEXT_OR_UI


# ---------------------------------------------------------------------------------------------
# Class vocabulary: a name a page writes must be a rule the sheet ships.
# ---------------------------------------------------------------------------------------------

_SEMANTIC_FAMILIES = ("bg", "text", "border", "on")


def _sheet_classes() -> set[str]:
    r"""Every class the SPA's own sheets define, with a variant selector read back to its class name.

    `.hover\:bg-secondary:hover` is the rule for a class literally called `hover:bg-secondary`: this
    SPA publishes its semantic colours as plain CSS, so the variant forms are written by hand and have
    to be recognised as such here.
    """
    names: set[str] = set()
    for path in (WEB / "src" / "styles").glob("*.css"):
        text = path.read_text(encoding="utf-8", errors="replace")
        names |= {selector.replace("\\", "") for selector in re.findall(r"\.([a-z](?:\\.|[a-z0-9-])*)", text)}
    return names


def _semantic_words(classes: set[str]) -> dict[str, set[str]]:
    """The colour words each semantic family already owns, measured from the classes it defines."""
    words: dict[str, set[str]] = {family: set() for family in _SEMANTIC_FAMILIES}
    for name in classes:
        family, _, word = name.split(":")[-1].partition("-")
        if family in words and word:
            words[family].add(word)
    return words


def _unshipped_semantic_class(token: str, classes: set[str], words: dict[str, set[str]]) -> bool:
    """True when a token claims one of our colour words and no rule behind it exists.

    Tailwind cannot compose this SPA's hand-written classes with its own variants or opacity
    modifiers, because it is never told about them -- there is no `@theme` block. So `bg-accent/10`
    and `hover:border-accent` render nothing: the control is wired, looks live and does not change.
    """
    family, _, word = token.split(":")[-1].split("/")[0].partition("-")
    if family not in _SEMANTIC_FAMILIES or word not in words[family]:
        return False
    return token not in classes


def _class_tokens() -> list[tuple[str, str]]:
    """`(file, token)` for every class-shaped word the SPA writes into a quoted string."""
    found: list[tuple[str, str]] = []
    for path in _web_sources():
        if path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for literal in re.findall(r'["`]([^"`\n]{1,400})["`]', text):
            if "var(" in literal:
                continue
            for token in re.split(r"[\s\n]+", literal):
                if token and "--" not in token and not token.startswith("/"):
                    found.append((str(path.relative_to(WEB)), token))
    return found


def test_no_page_writes_a_semantic_class_the_sheet_never_ships() -> None:
    classes = _sheet_classes()
    words = _semantic_words(classes)
    offenders = {
        f"{source}: {token}" for source, token in _class_tokens() if _unshipped_semantic_class(token, classes, words)
    }
    assert not offenders, "\n".join(sorted(offenders))


def test_the_semantic_class_detector_reads_the_compositions_it_forbids() -> None:
    classes = _sheet_classes()
    words = _semantic_words(classes)

    def probe(token: str) -> bool:
        return _unshipped_semantic_class(token, classes, words)

    assert probe("bg-accent/10"), "an opacity modifier on our own colour class ships no rule"
    assert probe("focus:text-accent"), "a variant Tailwind cannot compose ships no rule"
    assert not probe("text-accent"), "the plain class the sheet does ship"
    assert not probe("hover:bg-secondary"), "the variant form the sheet ships by hand"
    assert not probe("text-xs") and not probe("bg-white/5"), "a word the sheets never claimed is not ours to gate"


def test_every_button_class_a_page_writes_is_a_rule_the_sheet_ships() -> None:
    """A `btn-*` name with no rule behind it renders a button with its text and none of its surface."""
    classes = _sheet_classes()
    used = {token for _, token in _class_tokens() if token.startswith("btn-")}
    missing = sorted(used - classes)
    assert not missing, f"button classes with no rule behind them: {missing}"


def test_no_button_rule_ships_without_a_page_using_it() -> None:
    defined = {c for c in _sheet_classes() if c.startswith("btn-")}
    used = {token for _, token in _class_tokens() if token.startswith("btn-")}
    dead = sorted(defined - used)
    assert not dead, f"button rules nobody renders: {dead}"


# Tailwind resolves a size or weight utility from its own default theme whenever the generated sheet
# stays silent about that step, so `text-7xl` ships 7.25rem in a product whose largest token is
# 1.875rem, and `font-black` asks for 900 from faces whose variable axes stop at 700 -- the browser
# answers with the heaviest cut it has and nothing reports the lie. The two detectors below read what
# the scale declares and what the shipped files can draw, which is the only pair that can tell.
_DEFAULT_SIZE_STEPS = frozenset(
    {"xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "5xl", "6xl", "7xl", "8xl", "9xl"}
)
_TAILWIND_WEIGHTS = {
    "thin": 100,
    "extralight": 200,
    "light": 300,
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "bold": 700,
    "extrabold": 800,
    "black": 900,
}


def _declared_text_steps() -> set[str]:
    sheet = (WEB / "src" / "styles" / "tailwind-theme.css").read_text(encoding="utf-8")
    return {name[len("--text-") :] for name in re.findall(r"--text-[a-zA-Z0-9-]+", sheet)}


def _off_scale_type(text: str, scale: set[str]) -> list[str]:
    """Size utilities whose step the generated sheet never declared.

    `text-[var(--dt-…)]` is the house form for a token colour and is not a size, so the arbitrary
    value scan skips it; `text-[10px]` is a size nobody owns and is reported.
    """
    names = "|".join(sorted(_DEFAULT_SIZE_STEPS | scale, key=len, reverse=True))
    asked = {f"text-{step}" for step in re.findall(rf"\btext-({names})\b", text)}
    asked |= set(re.findall(r"\btext-\[(?!var\()[^\]]+\]", text))
    return sorted(asked - {f"text-{step}" for step in scale})


def _renderable_weight_intervals(css: str) -> list[tuple[int, int]]:
    """The [min, max] weights the declared `@font-face` blocks can actually draw."""
    return [(int(low), int(high or low)) for low, high in re.findall(r"font-weight:\s*(\d+)(?:\s+(\d+))?\s*[;}]", css)]


def _impossible_weights(text: str, intervals: list[tuple[int, int]]) -> list[str]:
    ceiling = max(high for _, high in intervals)
    floor = min(low for low, _ in intervals)
    asked = {
        f"font-{name} ({weight})"
        for name, weight in _TAILWIND_WEIGHTS.items()
        if re.search(rf"\bfont-{name}\b", text) and not floor <= weight <= ceiling
    }
    asked |= {
        f"font-weight: {weight}"
        for weight in re.findall(r"font-weight:\s*(\d+)\b", text)
        if not any(low <= int(weight) <= high for low, high in intervals)
    }
    return sorted(asked)


def test_no_component_asks_a_type_step_the_scale_does_not_declare() -> None:
    scale = _declared_text_steps()
    offenders = [
        f"{path.relative_to(WEB)}: {step}"
        for path in _web_sources()
        for step in _off_scale_type(path.read_text(encoding="utf-8", errors="replace"), scale)
    ]
    assert not offenders, "\n".join(offenders)


def test_no_component_asks_a_font_weight_no_shipped_face_can_draw() -> None:
    faces = (WEB / "src" / "styles" / "fonts.css").read_text(encoding="utf-8")
    intervals = _renderable_weight_intervals(faces)
    assert intervals, "fonts.css declares no @font-face weight, so nothing below can be measured"
    published = json.loads((DESIGN / "tokens.json").read_text(encoding="utf-8"))["typography"]["font-weight"]
    unreachable = [
        f"tokens.json publishes {name}={weight} outside {[f'{lo}-{hi}' for lo, hi in intervals]}"
        for name, weight in published.items()
        if not any(low <= int(weight) <= high for low, high in intervals)
    ]
    assert not unreachable, "\n".join(unreachable)
    # fonts.css is the capability, not a request for it.
    sources = [path for path in _web_sources() if path.name != "fonts.css"]
    offenders = [
        f"{path.relative_to(WEB)}: {ask}"
        for path in sources
        for ask in _impossible_weights(path.read_text(encoding="utf-8", errors="replace"), intervals)
    ]
    assert not offenders, "\n".join(offenders)


def test_the_type_and_weight_detectors_read_the_forms_they_forbid() -> None:
    scale = {"micro", "sm", "display"}
    assert _off_scale_type('className="text-7xl text-[10px] text-micro"', scale) == ["text-7xl", "text-[10px]"]
    assert _off_scale_type('className="text-sm text-[var(--dt-colors-text-link)]"', scale) == []
    assert _off_scale_type('className="text-lg"', scale) == ["text-lg"]
    intervals = _renderable_weight_intervals("@font-face { font-weight: 400 700; }")
    assert intervals == [(400, 700)]
    assert _impossible_weights('className="font-bold font-black"', intervals) == ["font-black (900)"]
    assert _impossible_weights("h1 { font-weight: 900; }", intervals) == ["font-weight: 900"]
    assert _impossible_weights('className="font-semibold"', intervals) == []


_RADIUS_DECLARATION = re.compile(r"border-radius:\s*([^;}\n]+)")


def _off_scale_corners(css: str) -> list[str]:
    """A corner an authored rule paints from a number the token scale never declared.

    `0`, `inherit` and percentages are geometry the scale has no word for (a hard edge, a circle), so
    they pass; a four-part corner is read part by part, because `0 0 var(--dt-…) var(--dt-…)` is one
    declaration in which only some of the parts are owned.
    """
    offenders: list[str] = []
    for value in _RADIUS_DECLARATION.findall(css):
        parts = [part for part in value.strip().split() if part not in {"0", "inherit"} and not part.endswith("%")]
        if any(not part.startswith("var(") for part in parts):
            offenders.append(value.strip())
    return offenders


def test_no_component_paints_a_corner_the_scale_does_not_own() -> None:
    """The sheet hands Tailwind every radius utility, so a component that writes `0.625rem` by hand is
    a corner no theme owns and no gate can move: five button and input rules carried 10px through the
    whole repaint while the landing painted the same control at 4px."""
    offenders: list[str] = []
    for path in _web_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(WEB)
        if path.suffix == ".css":
            offenders += [f"{rel}: border-radius: {hit}" for hit in _off_scale_corners(text)]
        offenders += [f"{rel}: {hit}" for hit in re.findall(r"\brounded-\[(?!var\()[^\]]+\]", text)]
    assert not offenders, "\n".join(offenders)


def test_the_corner_detector_reads_the_forms_it_forbids() -> None:
    assert _off_scale_corners("button { border-radius: 0.625rem; }") == ["0.625rem"]
    assert _off_scale_corners(".panel { border-radius: 1rem 1rem 0 0; }") == ["1rem 1rem 0 0"]
    assert _off_scale_corners(".chip { border-radius: var(--dt-border-radius-full); }") == []
    assert _off_scale_corners(".m { border-radius: 0 0 var(--radius) var(--radius); }") == []
    assert _off_scale_corners(".a { border-radius: 50%; }\n.b { border-radius: inherit; }") == []


# `var(--dt-radius-${rounded})` is invisible to the token-existence check above: no literal token name
# appears in the source, so nothing resolves it and a whole private namespace could hide there. The
# skeleton did exactly that -- it interpolated `--dt-radius-*`, an alias block index.css kept alive for
# no other user, and carried a `0.5rem` fallback that no theme can retune.
_DYNAMIC_VAR = re.compile(r"var\((--[a-z0-9-]+)-\$\{[^}]+\}([^)]*)\)")


def _dynamic_token_uses(text: str) -> list[tuple[str, str]]:
    return [(f"{m.group(1)}-", m.group(2).strip()) for m in _DYNAMIC_VAR.finditer(text)]


def test_a_dynamic_token_name_stays_inside_a_namespace_the_theme_owns() -> None:
    published = {theme: set(_theme_tokens(theme)) for theme in THEME_FILES}
    offenders: list[str] = []
    for path in _web_sources():
        for namespace, tail in _dynamic_token_uses(path.read_text(encoding="utf-8", errors="replace")):
            rel = path.relative_to(WEB)
            if not all(any(token.startswith(namespace) for token in tokens) for tokens in published.values()):
                offenders.append(f"{rel}: {namespace}${{…}} interpolates a namespace no theme publishes")
            if tail.startswith(","):
                offenders.append(f"{rel}: {namespace}${{…}} keeps the literal fallback {tail[1:].strip()!r}")
    assert not offenders, "\n".join(offenders)


def test_the_dynamic_token_reader_sees_the_alias_it_forbids() -> None:
    assert _dynamic_token_uses("borderRadius: `var(--dt-radius-${rounded}, 0.5rem)`") == [("--dt-radius-", ", 0.5rem")]
    assert _dynamic_token_uses("borderRadius: `var(--dt-border-radius-${rounded})`") == [("--dt-border-radius-", "")]
    assert _dynamic_token_uses("color: var(--dt-colors-accent-default)") == []


_STYLE_OBJECT = re.compile(r"\b([A-Za-z]*[sS]tyle)=\{\{")
_INLINE_SCALE_PROP = re.compile(r"\b(borderRadius|fontSize):\s*([^,}\n]+)")


def _object_body(text: str, open_at: int) -> str:
    """The declarations between the braces an attribute opened at `open_at`, one past the `{{`."""
    depth, cursor = 0, open_at - 2
    while cursor < len(text):
        char = text[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[open_at:cursor]
        cursor += 1
    raise AssertionError(f"style object at offset {open_at} is never closed")


def _inline_scale_literals(text: str) -> list[str]:
    """Corners and type sizes handed to a JSX style object as numbers or px strings.

    A style object becomes CSS, so a bare number is a value no theme and no token file can move. The
    ladder changed `border-radius.lg` and `xl` underneath ten chart tooltips that named 8 directly, and
    they kept painting the old corner while every card around them moved. Props a library consumes as
    data — Monaco's `options={{ fontSize: 14 }}`, a recharts axis tick — are not style objects, so they
    stay outside this reader rather than being forced into a string the library cannot parse.
    """
    offenders: list[str] = []
    for match in _STYLE_OBJECT.finditer(text):
        for prop in _INLINE_SCALE_PROP.finditer(_object_body(text, match.end())):
            value = prop.group(2).strip().strip("\"'`")
            if not value.startswith("var("):
                offenders.append(f"{prop.group(1)}: {prop.group(2).strip()}")
    return offenders


def test_no_component_hands_a_style_object_a_corner_or_type_size_the_tokens_cannot_move() -> None:
    offenders = [
        f"{path.relative_to(WEB)}: {offender}"
        for path in _web_sources()
        for offender in _inline_scale_literals(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not offenders, "JSX style objects carry literals the scale cannot retarget:\n" + "\n".join(offenders)


def test_the_style_object_reader_skips_props_a_library_needs_as_a_number() -> None:
    assert _inline_scale_literals("contentStyle={{ borderRadius: 8, fontSize: 12 }}") == [
        "borderRadius: 8",
        "fontSize: 12",
    ]
    assert _inline_scale_literals('style={{ borderRadius: "var(--dt-border-radius-lg)", fontSize: 12 }}') == [
        "fontSize: 12"
    ]
    assert _inline_scale_literals("options={{ fontSize: 14, padding: { top: 16 }, inlineSuggest: true }}") == []
    assert _inline_scale_literals("style={{ borderRadius: `var(--dt-border-radius-${rounded})` }}") == []


# ---------------------------------------------------------------------------
# Shadow tokens
# ---------------------------------------------------------------------------

#: A `--dt-shadow-*` token is a whole shadow, not a colour a rule can add its own offset to: every one of
#: them is printed from `tokens.json` as `offset-x offset-y [blur] [spread] color`. Composing one with a
#: length substitutes six or seven components into a grammar that takes five, which the engine then drops
#: at computed-value time -- `box-shadow: 0 0 16px var(--dt-shadow-glow-accent)` measures as `none` in a
#: live browser. The declaration is valid CSS text, so a bundler, a token diff and a screenshot taken
#: without a pointer on the element all agree with it; only the reader ever notices the elevation is gone.
_SHADOW_TOKEN_USE = re.compile(r"var\(--dt-shadow-[a-z0-9-]+\)")
_SHADOW_DECLARATION = re.compile(r"box-shadow\s*:\s*([^;{}]+)")


def _split_shadow_list(value: str) -> list[str]:
    """The items of a shadow list, split on the commas that separate them and not on the commas inside an
    `rgba()` colour -- Chromium reads the former as new shadows and the latter as one argument."""
    items: list[str] = []
    depth = 0
    current = ""
    for char in value:
        if char == "," and depth == 0:
            items.append(current)
            current = ""
            continue
        depth += char == "("
        depth -= char == ")"
        current += char
    items.append(current)
    return items


def _composed_shadows(css: str) -> list[str]:
    """Shadow declarations that spend a whole-shadow token as if it were one more component.

    A comma opens a new item of the list, and there the token substitutes into slots of its own: measured in
    Chromium, `inset 0 1px 0 <colour>, var(--dt-shadow-xl)` computes as the two shadows it names. Components
    sharing the token's item substitute six or seven into a grammar that reads five, and the engine drops the
    whole declaration. Only the second shape is an offender.
    """
    offenders: list[str] = []
    for match in _SHADOW_DECLARATION.finditer(css):
        for item in _split_shadow_list(match.group(1)):
            if not _SHADOW_TOKEN_USE.search(item):
                continue
            if re.search(r"\d", _SHADOW_TOKEN_USE.sub("", item)):
                offenders.append(" ".join(item.split()))
    return offenders


def _shipped_css_surfaces() -> dict[str, str]:
    """Every document this product ships CSS in: the SPA's sheets, the landing, and each surface whose
    stylesheet lives inside a Python, TypeScript or HTML file rather than a `.css`."""
    surfaces = {str(path.relative_to(ROOT)): path for path in (WEB / "src").rglob("*.css")}
    surfaces["site/styles.css"] = ROOT / "site" / "styles.css"
    surfaces.update(OFFLINE_SHEETS)
    return {
        label: path.read_text(encoding="utf-8", errors="replace") for label, path in surfaces.items() if path.is_file()
    }


def test_no_rule_spends_a_shadow_token_as_if_it_were_a_colour() -> None:
    offenders: list[str] = []
    for label, css in _shipped_css_surfaces().items():
        offenders.extend(f"{label}: box-shadow: {offender}" for offender in _composed_shadows(css))
    assert not offenders, "these shadows substitute to an invalid list and compute to none:\n" + "\n".join(offenders)


def test_the_shadow_reader_sees_the_composition_it_forbids() -> None:
    assert _composed_shadows("box-shadow: 0 0 16px var(--dt-shadow-glow-accent);") == [
        "0 0 16px var(--dt-shadow-glow-accent)"
    ]
    assert _composed_shadows("box-shadow: var(--dt-shadow-glow-accent);") == []
    # A list is not a composition: each item keeps its own slots, and the browser computes both shadows.
    assert (
        _composed_shadows("box-shadow: inset 0 1px 0 var(--dt-colors-surface-inset-highlight), var(--dt-shadow-xl);")
        == []
    )
    # The commas of an rgba() colour belong to one argument, not to a second item of the list.
    assert _composed_shadows("box-shadow: 0 0 16px rgba(139, 92, 246, 0.25) var(--dt-shadow-glow-accent);") == [
        "0 0 16px rgba(139, 92, 246, 0.25) var(--dt-shadow-glow-accent)"
    ]
    assert _composed_shadows("box-shadow: var(--dt-shadow-sm), var(--dt-shadow-float);") == []
    # A colour token inside a hand-written shadow is the ordinary case and stays legal.
    assert _composed_shadows("box-shadow: 0 1px 2px var(--dt-colors-accent-muted);") == []
    assert _composed_shadows("box-shadow: none;") == []


# ---------------------------------------------------------------------------
# Colour written into an element's own `style` attribute
# ---------------------------------------------------------------------------

#: React turns `style={{…}}` into the element's `style` attribute, and an attribute outranks every rule
#: in the sheet: the tint a `.btn-soft-*` publishes, the `:hover` edge, the `:focus` ring, the disabled
#: treatment. The pair a contrast gate measures for that class is then not the pair a reader sees -- one
#: of these on a Pause button is what shipped a 4.38:1 label that every static rule in this file called
#: compliant. A colour the sheet already names has to be asked for by name.
_DOM_STYLE_OBJECT = re.compile(r"(?<![\w-])style=\{\{")
_COLOUR_PROPERTY = re.compile(
    r"\b(?:color|background|backgroundImage|backgroundColor|borderColor|border(?:Top|Right|Bottom|Left)Color"
    r"|outlineColor|boxShadow|textShadow)\s*:\s*([^,}\n]*)"
)
_TOKEN_IN_VALUE = re.compile(r"--dt-(?:colors|shadow)")


def _inline_token_colours(text: str) -> list[str]:
    offenders: list[str] = []
    for match in _DOM_STYLE_OBJECT.finditer(text):
        for declaration in _COLOUR_PROPERTY.finditer(_object_body(text, match.end())):
            if _TOKEN_IN_VALUE.search(declaration.group(1)):
                offenders.append(declaration.group(0).strip())
    return offenders


def test_no_dom_element_carries_a_colour_that_outranks_the_sheet() -> None:
    offenders: list[str] = []
    for path in _web_sources():
        if path.suffix != ".tsx":
            continue
        offenders.extend(
            f"{path.relative_to(WEB)}: {offender}"
            for offender in _inline_token_colours(path.read_text(encoding="utf-8", errors="replace"))
        )
    assert not offenders, "\n".join(offenders)


def test_the_inline_colour_reader_reads_the_forms_it_forbids() -> None:
    assert _inline_token_colours('<button style={{ color: "var(--dt-colors-status-warning)" }} />') == [
        'color: "var(--dt-colors-status-warning)"'
    ]
    assert _inline_token_colours('<div style={{ backgroundColor: s.bg, color: "var(--dt-colors-text-link)" }} />') == [
        'color: "var(--dt-colors-text-link)"'
    ]
    # Geometry and data are not colours the sheet ships.
    assert _inline_token_colours('<div style={{ width: "50%", backgroundColor: p.hex }} />') == []
    # A library's own style object and its paint props are not attributes this sheet can reach.
    assert _inline_token_colours('<Tooltip contentStyle={{ color: "var(--dt-colors-x)" }} />') == []
    assert _inline_token_colours('<Area stroke="var(--dt-colors-accent-default)" fill="url(#grad)" />') == []


# ---------------------------------------------------------------------------
# A token spent as an arbitrary class value
# ---------------------------------------------------------------------------

#: `bg-[var(--dt-colors-bg-hover)]` asks Tailwind to mint a utility whose colour the sheet already publishes
#: under a name. The pair a contrast gate measures for `bg-hover` never reaches the element: the value is a
#: string inside a bracket, and a theme that changes the token changes nothing on the page.
_CLASS_TOKEN_BRACKET = re.compile(r"[\w-]*-\[(?:var\()?--dt-(?:colors|shadow)[^\]]*\]")


def _class_token_brackets(text: str) -> list[str]:
    """Class values that spend a colour or a shadow token by value."""
    return [match.group(0) for match in _CLASS_TOKEN_BRACKET.finditer(text)]


def test_no_class_bracket_spends_a_colour_token_by_value() -> None:
    offenders: list[str] = []
    for path in _web_sources():
        if path.suffix not in {".tsx", ".ts"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        offenders.extend(f"{path.relative_to(WEB)}: {offender}" for offender in _class_token_brackets(text))
    assert not offenders, "\n".join(offenders)


def test_the_class_bracket_reader_notices_a_token_spent_by_value() -> None:
    assert _class_token_brackets('<div className="bg-[var(--dt-colors-bg-hover)]" />') == [
        "bg-[var(--dt-colors-bg-hover)]"
    ]
    assert _class_token_brackets('<div className="hover:text-[--dt-colors-text-link]" />') == [
        "text-[--dt-colors-text-link]"
    ]
    assert _class_token_brackets("<div className={`border-[var(--dt-colors-accent-muted)] p-2`} />") == [
        "border-[var(--dt-colors-accent-muted)]"
    ]
    # Geometry from the scale is what the bracket exists for; a colour is not.
    assert (
        _class_token_brackets('<div className="rounded-[var(--dt-border-radius-lg)] w-[var(--dt-spacing-4)]" />') == []
    )

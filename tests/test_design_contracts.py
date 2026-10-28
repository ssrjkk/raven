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
    # The second stop of the brand gradient carries text in .gradient-text, so it needs text contrast.
    (("brand", "secondary"), ("bg", "primary"), NORMAL_TEXT),
    # Canvas text and canvas edges in the knowledge graph are painted from these, once a frame.
    (("text", "secondary"), ("surface", "card"), NORMAL_TEXT),
    (("text", "tertiary"), ("surface", "card"), LARGE_TEXT_OR_UI),
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
        and path.name != "themes.css"
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


def test_the_generated_sheet_equals_the_token_files_and_is_loaded() -> None:
    """A generated sheet is only trustworthy while the generator still agrees with it, and a sheet the
    SPA never imports paints nothing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_theme_css", ROOT / "scripts" / "gen_theme_css.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sheet = WEB / "src" / "styles" / "themes.css"
    rendered = module.render()
    assert sheet.read_text(encoding="utf-8") == rendered, "themes.css is stale — run python scripts/gen_theme_css.py"
    assert '@import "./themes.css";' in (WEB / "src" / "styles" / "index.css").read_text(encoding="utf-8")
    for selector in (':root,\n[data-theme="dark"]', '[data-theme="light"]', '[data-theme="midnight"]'):
        assert selector in rendered, f"{selector} block missing from the sheet"



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
}


def _region_of(text: str, generator: Any) -> str:
    start = text.index(generator.SENTINEL_START)
    end = text.index(generator.SENTINEL_END, start) + len(generator.SENTINEL_END)
    return text[start:end]


@pytest.mark.parametrize("label", sorted(OFFLINE_SHEETS))
def test_offline_surfaces_embed_the_generated_token_region(label: str) -> None:
    """The two surfaces never load the SPA bundle, so they used to hand-copy a palette. The copy
    drifted: the webchat page invented #8b5cf6 as its button surface and put white on it at 4.23:1.
    The region between the sentinels is generated output, checked byte for byte, and every token the
    sheet references has to be declared inside it."""
    generator = _load_theme_generator()
    text = OFFLINE_SHEETS[label].read_text(encoding="utf-8", errors="replace")
    region = _region_of(text, generator)
    assert region == generator.surface_block(), f"{label}: embedded region is not what the generator emits"

    declared = set(re.findall(r"^\s*(--dt-[a-zA-Z0-9-]+):", region, re.M))
    body = re.sub(r"\s*" + re.escape(generator.SENTINEL_START) + r".*" + re.escape(generator.SENTINEL_END), "", text, flags=re.S)
    referenced = set(re.findall(r"var\(\s*(--dt-[a-zA-Z0-9-]+)", body))
    dangling = sorted(referenced - declared)
    assert not dangling, f"{label} references tokens its region does not declare: {dangling}"

    # the sheet's own short names are part of the contract too: an alias no rule reads is a colour
    # someone will later assume is live
    aliases = re.findall(r"^\s{2}(--(?!dt-)[a-z-]+):", body, re.M)
    used = set(re.findall(r"var\(\s*(--[a-z-]+)", body))
    unused = sorted(name for name in aliases if name not in used)
    assert not unused, f"{label} declares aliases nothing uses: {unused}"


@pytest.mark.parametrize("label", sorted(OFFLINE_SHEETS))
def test_offline_surfaces_carry_no_colour_of_their_own(label: str) -> None:
    """Outside the generated region these sheets may not name a colour: that is how the private
    palette got written in the first place."""
    generator = _load_theme_generator()
    text = OFFLINE_SHEETS[label].read_text(encoding="utf-8", errors="replace")
    body = text.replace(_region_of(text, generator), "")
    offenders = [
        f"{label}:{i}: {hit}"
        for i, line in enumerate(body.splitlines(), 1)
        for hit in _COLOUR_LITERAL.findall(line)
    ]
    assert not offenders, "\n".join(offenders)


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
    )
    for label, foreground, background, minimum in pairs:
        ratio = contrast(foreground, background)
        assert ratio >= minimum, f"{label}: {foreground} on {background} = {ratio:.2f}:1, need {minimum}"



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


def _over(foreground: tuple[float, float, float, float], background: tuple[float, float, float]) -> tuple[float, float, float]:
    if foreground[3] >= 1.0:
        return foreground[:3]
    alpha = foreground[3]
    return tuple(foreground[i] * alpha + background[i] * (1 - alpha) for i in range(3))  # type: ignore[return-value]


def _hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(c))) for c in rgb])


def test_landing_labels_are_readable_on_every_panel_they_paint_on() -> None:
    """The storefront is the surface a buyer reads first, and it keeps its own brand scale rather than
    the SPA tokens, so nothing else in this suite would notice it regressing. Every rule that declares a
    label and a background is measured: a translucent surface is composited over each dark panel it
    could sit on and the worst answer is the one kept, because the rule does not say which ancestor it
    lands on. This is what found white on --violet at 4.23:1 in ::selection and in the primary button's
    gradient stop."""
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
    and the plugin tag badges. Each is a fill -- a UI part at 3:1 -- and also the label colour of a
    soft badge, so the scale is held to the text minimum of 4.5:1 against the panel it is drawn on."""
    colors = _palette(theme)
    card = colors["surface"]["card"]
    category = colors["category"]
    assert set(category) == {
        "blue", "green", "amber", "violet", "pink", "cyan", "orange", "teal", "yellow", "purple",
        "indigo", "red", "lime", "slate", "grey",
    }, f"{theme}: the categorical scale is not the fifteen named hues"
    for name, value in category.items():
        ratio = contrast(value, card)
        assert ratio >= NORMAL_TEXT, f"{theme}: category.{name} {value} on surface.card = {ratio:.2f} < 4.5"
    assert len(set(category.values())) == len(category), f"{theme}: duplicate categorical colours"
    hues = [_hsl(value)[0] for value in category.values()]
    assert max(hues) - min(hues) >= 120, f"{theme}: the categorical hues do not span the wheel"

    # paint.ts picks the badge label from the theme's two inverses, whichever reads better on the
    # fill; the picker is only safe if at least one of them clears AA for every slot of the scale.
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
    mixed = tuple(round(colour * alpha + other * (1 - alpha)) for colour, other in zip((red, green, blue), back, strict=True))
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
                    offenders.append(
                        f"{selector.strip()[:48]}: {token}={value} on {theme} card {card} = {ratio:.2f}:1"
                    )
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

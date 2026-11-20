"""The storefront and the product are one design, and this measures that instead of trusting it.

`site/styles.css` and `web/src/design/tokens.json` are two files that can each say a colour, a
corner, a duration and a typeface. Until the SPA was repainted onto the landing's scale they
described two palettes -- the buyer's page at `#0a0812`/`#8b5cf6`, the app behind it at
`#0f1117`/`#7c3aed` -- and nothing in the suite could see the difference because each file was only
ever compared with itself. Every role below is a pair the two surfaces are meant to agree on, and the
comparison reads the shipped files, so a repaint on one side fails the build on the other.

A parity check is worth nothing if its parser is broken, so the drift test plants a change into one
role and requires the comparison to name that role.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html import unescape
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITE_CSS = ROOT / "site" / "styles.css"
DESIGN = ROOT / "web" / "src" / "design"
STYLES = ROOT / "web" / "src" / "styles"

Color = tuple[float, float, float, float]


def site_variables(css: str) -> dict[str, str]:
    """The landing's `:root` block as a name -> declaration table."""
    block = css.split(":root {", 1)[1].split("\n}", 1)[0]
    return dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block))


def app_tokens() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((DESIGN / "tokens.json").read_text(encoding="utf-8"))
    return loaded


def token_at(data: dict[str, Any], dotted: str) -> str:
    node: Any = data
    for part in dotted.split("."):
        assert isinstance(node, dict), f"tokens.json has no {dotted}"
        node = node[part]
    assert isinstance(node, str), f"tokens.json {dotted} is not a scalar"
    return node


def parse_color(text: str, site: dict[str, str]) -> Color | None:
    """A colour declaration reduced to channels, including the landing's `color-mix()` formula."""
    value = text.strip()
    if m := re.fullmatch(r"#([0-9a-fA-F]{6})", value):
        bits = int(m.group(1), 16)
        return (((bits >> 16) & 255) / 255, ((bits >> 8) & 255) / 255, (bits & 255) / 255, 1.0)
    if m := re.fullmatch(r"#([0-9a-fA-F]{3})", value):
        channels = [int(c * 2, 16) / 255 for c in m.group(1)]
        return (channels[0], channels[1], channels[2], 1.0)
    if m := re.fullmatch(r"rgba?\(([^)]+)\)", value):
        parts = [p for p in re.split(r"[,/\s]+", m.group(1).strip()) if p]
        if len(parts) == 3:
            parts.append("1")
        channels = [float(c) / 255 for c in parts[:3]]
        return (channels[0], channels[1], channels[2], float(parts[3]))
    if m := re.fullmatch(r"color-mix\(in srgb,\s*var\((--[a-z0-9-]+)\)\s*([\d.]+)%,\s*transparent\)", value):
        inner = parse_color(site_variables(SITE_CSS.read_text(encoding="utf-8"))[m.group(1)], site)
        if inner is None:
            return None
        share = float(m.group(2)) / 100
        return (*inner[:3], share)
    if m := re.fullmatch(r"var\((--[a-z0-9-]+)\)", value):
        return parse_color(site[m.group(1)], site)
    return None


def first_family(stack: str) -> str:
    """The family a browser actually asks for first, whatever quoting each file happens to use."""
    lead = stack.split(",")[0].strip().strip("\"'")
    return lead.lower()


def ease(stack: str) -> str:
    return re.sub(r"\s+", "", stack.strip())


# site variable -> (app token path, how to compare it, what the role is)
PARITY: list[tuple[str, str, str, str]] = [
    ("--bg", "colors.bg.primary", "color", "page ground"),
    ("--bg-panel", "colors.bg.secondary", "color", "sidebar and panel ground"),
    ("--bg-card", "colors.surface.card", "color", "card ground"),
    ("--bg-raised", "colors.surface.elevated", "color", "raised surface, menus"),
    ("--ink", "colors.text.primary", "color", "primary text"),
    ("--ink-mute", "colors.text.secondary", "color", "secondary text"),
    ("--on-violet", "colors.text.on-accent", "color", "label on an accent surface"),
    ("--violet-surface", "colors.accent.default", "color", "accent surface a white label sits on"),
    ("--violet-deep", "colors.accent.hover", "color", "accent pressed"),
    ("--violet", "colors.chart.series-1", "color", "identity violet, drawn without a label"),
    ("--violet-text", "colors.text.link", "color", "link and focus text"),
    ("--violet-bright", "colors.text.link-hover", "color", "link hovered"),
    ("--fuchsia", "colors.brand.secondary", "color", "second brand hue"),
    ("--danger", "colors.status.error", "color", "error ink"),
    ("--hairline", "colors.border.default", "color", "the rule around every panel"),
    ("--hairline-strong", "colors.border.hover", "color", "rule on an interactive edge"),
    ("--violet-wash", "colors.accent.subtle", "color", "accent wash behind an active row"),
    ("--radius", "border-radius.md", "length", "the one corner radius"),
    ("--dur-fast", "animation.duration.fast", "length", "quick state change"),
    ("--dur", "animation.duration.normal", "length", "default transition"),
    ("--dur-slow", "animation.duration.slow", "length", "entrance and reveal"),
    ("--ease-out", "animation.easing.out", "ease", "the deceleration curve"),
    ("--ease-spring", "animation.easing.spring", "ease", "the overshoot curve"),
    ("--font-body", "typography.font-family.sans", "family", "body typeface"),
    ("--font-mono", "typography.font-family.mono", "family", "data and label typeface"),
    ("--font-display", "typography.font-family.display", "family", "display typeface"),
]


def drift(site: dict[str, str], tokens: dict[str, Any]) -> list[str]:
    """Every parity role the two files disagree on, described enough to fix without re-reading them."""
    offenders: list[str] = []
    for name, path, kind, role in PARITY:
        if name not in site:
            offenders.append(f"site/styles.css declares no {name} ({role})")
            continue
        declared = token_at(tokens, path)
        if kind == "color":
            left, right = parse_color(site[name], site), parse_color(declared, site)
            if left is None or right is None:
                offenders.append(f"{role}: unparseable pair {site[name]!r} / {declared!r}")
            elif max(abs(a - b) for a, b in zip(left, right, strict=True)) > 1 / 255:
                offenders.append(f"{role}: site {name} = {site[name]} but tokens.json {path} = {declared}")
        elif kind == "family":
            if first_family(site[name]) != first_family(declared):
                offenders.append(
                    f"{role}: site leads with {first_family(site[name])}, app with {first_family(declared)}"
                )
        else:
            if ease(site[name]) != ease(declared):
                offenders.append(f"{role}: site {name} = {site[name]} but tokens.json {path} = {declared}")
    return offenders


def test_the_app_paints_the_landing_scale() -> None:
    tokens = app_tokens()
    site = site_variables(SITE_CSS.read_text(encoding="utf-8"))
    offenders = drift(site, tokens)
    assert not offenders, "the storefront and the SPA disagree on:\n" + "\n".join(offenders)


def test_the_parity_comparison_notices_a_drifted_role() -> None:
    """The check must fail when only one side moves, or it is a test that reads its own assumptions."""
    tokens = app_tokens()
    site = site_variables(SITE_CSS.read_text(encoding="utf-8"))
    assert drift(site, tokens) == [], "parity is already broken; the mutation below proves nothing"

    mutated = json.loads(json.dumps(tokens))
    mutated["colors"]["bg"]["primary"] = "#0f1117"
    found = drift(site, mutated)
    assert len(found) == 1 and "page ground" in found[0], f"an 8-bit move on the page ground read as {found}"

    mutated = json.loads(json.dumps(tokens))
    mutated["colors"]["border"]["default"] = "rgba(42, 45, 62, 1)"
    assert "the rule around every panel" in drift(site, mutated)[0], "an opaque border passed as a hairline"

    mutated = json.loads(json.dumps(tokens))
    mutated["typography"]["font-family"]["sans"] = '"Inter", system-ui, sans-serif'
    assert "body typeface" in drift(site, mutated)[0], "a swapped typeface passed as parity"

    mutated = json.loads(json.dumps(tokens))
    mutated["animation"]["duration"]["slow"] = "400ms"
    assert "entrance and reveal" in drift(site, mutated)[0], "a retimed entrance passed as parity"


def test_the_app_names_the_landing_faces_and_ships_them_with_cyrillic() -> None:
    """A Russian-facing UI that names a Latin-only webfont renders its Cyrillic in the system font.

    The landing itself ships latin-only files; the SPA has to carry the Cyrillic subsets too, so this
    checks the faces fonts.css declares exist on disk and that every family the tokens lead with has a
    Cyrillic range somewhere in that sheet.
    """
    tokens = app_tokens()
    fonts = (STYLES / "fonts.css").read_text(encoding="utf-8")
    families = {
        first_family(token_at(tokens, f"typography.font-family.{role}")) for role in ("sans", "mono", "display")
    }
    declared = {first_family(m) for m in re.findall(r"font-family:\s*([^;]+);", fonts)}
    assert families <= declared, f"tokens name {sorted(families - declared)} but fonts.css declares no face"

    urls = set(re.findall(r"url\('/fonts/([^']+)'\)", fonts))
    for name in urls:
        assert (ROOT / "web" / "public" / "fonts" / name).read_bytes()[:4] == b"wOF2", f"{name} is not a woff2"
    for family in families:
        blocks = re.findall(r"@font-face\s*\{[^}]*\}", fonts)
        own = [
            b
            for b in blocks
            if (face := re.search(r"font-family:\s*([^;]+);", b)) and first_family(face.group(1)) == family
        ]
        assert own, f"{family} has no @font-face"
        if family != "space grotesk":
            assert any("U+0400-045F" in b for b in own), f"{family} ships no Cyrillic subset"

    for stale in ("Inter", "JetBrains Mono"):
        assert stale not in (STYLES / "index.css").read_text(encoding="utf-8"), f"index.css still names {stale}"


def test_tailwind_utilities_resolve_to_the_token_scale() -> None:
    """`rounded-lg` in 126 components is a second radius scale unless the theme sheet ties it to the tokens."""
    sheet = STYLES / "tailwind-theme.css"
    index = (STYLES / "index.css").read_text(encoding="utf-8")
    assert sheet.exists(), "web/src/styles/tailwind-theme.css is missing — run python scripts/gen_theme_css.py"
    assert '@import "./tailwind-theme.css";' in index, "the SPA never loads the Tailwind theme sheet"
    assert index.index('@import "tailwindcss"') < index.index('@import "./tailwind-theme.css"'), (
        "the theme sheet must come after tailwindcss or its defaults win"
    )

    theme = dict(re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", sheet.read_text(encoding="utf-8")))
    tokens = app_tokens()
    assert theme["--radius-lg"] == token_at(tokens, "border-radius.lg"), "rounded-lg ignores the card step"
    assert theme["--radius-xl"] == token_at(tokens, "border-radius.xl"), "rounded-xl keeps Tailwind's own 12px"
    assert theme["--radius-3xl"] == token_at(tokens, "border-radius.xl"), (
        "nothing ships rounder than the landing's biggest card"
    )
    assert first_family(theme["--font-sans"]) == first_family(token_at(tokens, "typography.font-family.sans"))
    assert ease(theme["--ease-out"]) == ease(token_at(tokens, "animation.easing.out"))


def _is_generated(text: str) -> bool:
    """The two sheets this repo generates from the token files, recognised by their own header."""
    return "gen_theme_css.py" in text[:300].lower()


def test_motion_in_the_stylesheets_has_only_the_token_numbers() -> None:
    """Durations written as literals cannot be retuned by the theme, and the landing's rhythm is 160/320/620.

    A looping ambient rhythm -- the typing dots, a spinner -- is not a state transition, so it keeps
    its own timing; the `prefers-reduced-motion` kill switch keeps its 0.01ms idiom.
    """
    offenders: list[str] = []
    for css in sorted(STYLES.glob("*.css")):
        text = css.read_text(encoding="utf-8")
        if _is_generated(text):
            continue
        for rule, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            if "{" in rule or "*/" in rule:
                continue  # the scanner matched a comment as a selector; a real rule follows
            for prop, value in re.findall(r"(transition|animation)([^;]*);", body):
                if value.lstrip().startswith("-delay") or "infinite" in value:
                    continue  # choreography and ambient loops are not the motion language
                if re.search(r"\d+(?:\.\d+)?m?s\b", value) and "0.01ms" not in value:
                    offenders.append(f"{css.name} {rule.strip()[:40]}: {prop}{value.strip()[:60]}")
                elif re.search(r"\bease(-in|-out)?\b", value):
                    offenders.append(
                        f"{css.name} {rule.strip()[:40]}: {prop}{value.strip()[:60]} names a curve, not a token"
                    )
    assert not offenders, "literal motion values outside the tokens:\n" + "\n".join(offenders)


def test_no_colour_literal_survives_outside_the_token_layer() -> None:
    """The repaint is only real if nothing downstream of the tokens still carries the old hexes."""
    offenders: list[str] = []
    for path in (ROOT / "web" / "src").rglob("*"):
        if path.suffix not in {".css", ".tsx", ".ts"} or path.is_dir():
            continue
        if path.parent == DESIGN and path.name.startswith("tokens"):
            continue
        # accent presets and the tests that assert them declare hexes on purpose
        if path.name == "accent.ts" or ".test." in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _is_generated(text):
            continue
        for line in text.splitlines():
            if re.search(r"#[0-9a-fA-F]{6}\b", line) and not line.strip().startswith(("//", "*", "/*")):
                offenders.append(f"{path.name}:{line.strip()[:70]}")
    assert not offenders, "colour literals outside web/src/design:\n" + "\n".join(offenders[:20])


_NAMED_COLOUR_UTILITY = re.compile(
    r"(?<![\w-])(?:bg|text|border|ring|fill|stroke|from|to|via|shadow|outline|accent|caret)-"
    r"(?:white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|"
    r"sky|blue|indigo|violet|purple|fuchsia|pink|rose)(?:-\d{2,3})?(?:/\d+)?"
    r"(?![\w-])"
)


def named_colour_utilities(text: str) -> list[str]:
    """Tailwind utilities that name a colour instead of a token, including the `/60` alpha form."""
    return _NAMED_COLOUR_UTILITY.findall(text)


def test_no_component_paints_a_colour_the_theme_cannot_move() -> None:
    """`bg-black/60` over a light popover, `ring-white/10` on a white panel: a Tailwind colour utility
    resolves from Tailwind's own scale, so the theme switch and the accent picker cannot reach it and the
    component silently keeps a colour from a palette the repaint abandoned. Measured on this tree before
    the fix: a scrim at 60% black where the light theme declares 45%, a rim light of white that paints
    nothing at all on a white surface, and an artifact pane on bare `bg-white`.
    """
    offenders: list[str] = []
    for path in (ROOT / "web" / "src").rglob("*.tsx"):
        if ".test." in path.name:
            continue
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            hits = named_colour_utilities(line)
            if hits:
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{line_no}: {', '.join(sorted(set(hits)))}")
    assert not offenders, "components naming a Tailwind colour instead of a token:\n" + "\n".join(offenders[:20])


def test_the_named_colour_scanner_sees_the_alpha_form_and_the_scale() -> None:
    """The guard above is only worth its claim if this parser reads the shapes components actually use."""
    assert named_colour_utilities('className="fixed inset-0 bg-black/60 backdrop-blur-sm"') == ["bg-black/60"]
    assert named_colour_utilities('className="ring-1 ring-white/10"') == ["ring-white/10"]
    assert named_colour_utilities('className="border border-default bg-secondary"') == []
    assert named_colour_utilities('className="bg-[var(--dt-colors-overlay-scrim)]"') == []


def test_the_repainted_surfaces_carry_no_leftover_from_the_old_scale() -> None:
    """Every surface outside the SPA bundle that says Raven's colours, checked against the old page.

    The storefront and the app drifted because five documents each kept their own copy of the palette
    -- a splash screen, a manifest, two icons, an MV3 popup, an offline chat page and a VS Code
    webview -- and a repaint of `tokens.json` reaches none of them unless they are regenerated.
    The old page ground is the marker: if it survives anywhere here, that surface is still painting
    the pre-repaint product.
    """
    retired = ("#0f1117", "#1a1d2e", "#1e2140", "#2a2d3e", "#e4e4e7", "#a1a1aa", "#a079f8")
    surfaces = (
        ROOT / "web" / "index.html",
        ROOT / "web" / "public" / "offline.html",
        ROOT / "web" / "public" / "manifest.json",
        ROOT / "web" / "public" / "icons" / "icon-192.svg",
        ROOT / "web" / "public" / "icons" / "icon-512.svg",
        ROOT / "extension" / "src" / "popup" / "popup.css",
        ROOT / "extension" / "vscode" / "src" / "panel.ts",
        ROOT / "raven" / "channels" / "webchat" / "channel.py",
    )
    offenders = [
        f"{path.relative_to(ROOT)}: {hex_}"
        for path in surfaces
        for hex_ in retired
        if hex_ in path.read_text(encoding="utf-8")
    ]
    assert not offenders, "surfaces still on the pre-repaint palette:\n" + "\n".join(offenders)


_SHELL_BRANCH = re.compile(
    r"theme === 'midnight' \? '#([0-9a-f]{6})' : theme === 'light' \? '#([0-9a-f]{6})' : '#([0-9a-f]{6})'"
)
_SHELL_META = re.compile(r'<meta name="theme-color" content="#([0-9a-f]{6})"')


def shell_grounds(html: str) -> dict[str, str]:
    """The page ground the pre-hydration script picks per theme, plus the static one it paints first."""
    branch = _SHELL_BRANCH.search(html)
    assert branch is not None, "web/index.html no longer chooses a theme-color per theme, so this parser is blind"
    meta = _SHELL_META.search(html)
    assert meta is not None, "web/index.html carries no static theme-color"
    midnight, light, dark = ("#" + group for group in branch.groups())
    return {"midnight": midnight, "light": light, "dark": dark, "first paint": f"#{meta.group(1)}"}


def test_the_html_shell_paints_the_ground_every_theme_actually_paints() -> None:
    """The browser colours the tab and the mobile status bar from `web/index.html`, long before
    `ThemeContext` rewrites the meta after mount, so the shell carries one ground per theme and each has
    to be the page colour that theme's tokens declare. This was the surface the repaint reached last: the
    SPA's own HTML still named the pre-repaint `#0f1117` after every stylesheet had moved on."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    grounds = shell_grounds(html)
    for theme, name in (("dark", "tokens.json"), ("light", "tokens.light.json"), ("midnight", "tokens.midnight.json")):
        declared = token_at(json.loads((DESIGN / name).read_text(encoding="utf-8")), "colors.bg.primary")
        assert grounds[theme] == declared, f"{theme}: the shell paints {grounds[theme]}, the theme paints {declared}"
    assert grounds["first paint"] == grounds["dark"], "the static meta disagrees with what dark paints"


def test_the_shell_ground_reader_notices_a_theme_left_behind() -> None:
    """Three literals and three themes: the reader has to fail when one of them stops matching."""
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    drifted = shell_grounds(html.replace("#06040c", "#050507", 1))
    midnight = token_at(json.loads((DESIGN / "tokens.midnight.json").read_text(encoding="utf-8")), "colors.bg.primary")
    assert drifted["midnight"] == "#050507" != midnight


def test_the_offline_surfaces_embed_what_the_generator_now_prints() -> None:
    """The embedded regions are copies; a copy is only true while someone regenerates it.

    The host list is the generator's own registration, so a surface registered there is policed here
    without anyone remembering to name it twice.
    """
    gen = _generator()
    blocks = {"--print-surface": gen.surface_block(), "--print-scaffold": gen.scaffold_block()}
    for command, hosts in gen.REGION_HOSTS.items():
        start, _end = gen._surface_sentinels(command)
        for rel in hosts:
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert blocks[command] in text, f"{rel} embeds a stale {command} region"
            assert text.count(start) == 1, f"{rel} holds the {command} region more than once"


#: Where a hand-pasted region can hide. Built output is absent on purpose: `web/dist` and `out` hold a
#: copy of a copy, and regenerating those is a build step rather than an edit a gate can act on.
_REGION_SCAN_ROOTS = ("raven", "aios", "ravencode", "web/src", "web/public", "extension", "site")
_REGION_SCAN_SKIP = {"node_modules", "dist", "out", "build", "__pycache__"}
_REGION_SCAN_SUFFIXES = {".css", ".html", ".js", ".py", ".ts", ".tsx"}


def documents_pasting_a_region(gen: Any, roots: tuple[Path, ...], heads: list[str] | None = None) -> set[Path]:
    """Every source document under ``roots`` that carries a generated region between its sentinels.

    The heads default to the palette's, because that is the region most surfaces paste; a caller
    measuring the faces passes their markers and gets the same sweep for them.
    """
    heads = heads or [gen._surface_sentinels(command)[0] for command in gen.REGION_HOSTS]
    found: set[Path] = set()
    for root in roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _REGION_SCAN_SUFFIXES or _REGION_SCAN_SKIP & set(path.parts):
                continue
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(head in text for head in heads):
                found.add(path)
    return found


def test_no_document_pastes_a_region_the_registration_does_not_cover() -> None:
    """A fifth surface can copy the palette today, and a gate that reads a fixed list of four will never
    notice it drift. The sweep is the other half of that list."""
    gen = _generator()
    scanned = documents_pasting_a_region(gen, tuple(ROOT / name for name in _REGION_SCAN_ROOTS))
    registered = {ROOT / rel for hosts in gen.REGION_HOSTS.values() for rel in hosts}
    assert scanned, "the sweep reads nothing, which is how a gate like this passes by accident"
    assert scanned == registered, (
        f"unregistered pasted regions: {sorted(p.relative_to(ROOT) for p in scanned - registered)}"
    )


def test_the_region_sweep_notices_a_document_nobody_registered(tmp_path: Path) -> None:
    gen = _generator()
    start, end = gen._surface_sentinels("--print-surface")
    stray = tmp_path / "stray.css"
    stray.write_text(f":root {{\n{start}\n{gen.surface_block()[len(start) : -len(end)]}{end}\n}}\n", encoding="utf-8")
    assert documents_pasting_a_region(gen, (tmp_path,)) == {stray}, "a pasted region escaped the sweep"
    assert documents_pasting_a_region(gen, (tmp_path.parent,)) >= {stray}


@pytest.mark.parametrize("theme", ["tokens.light.json", "tokens.midnight.json"])
def test_every_theme_publishes_the_same_roles_as_the_identity_theme(theme: str) -> None:
    identity = app_tokens()
    other = json.loads((DESIGN / theme).read_text(encoding="utf-8"))

    def paths(node: dict[str, Any], prefix: str = "") -> set[str]:
        out: set[str] = set()
        for key, value in node.items():
            if key.startswith("$") or key in {"description", "version"}:
                continue
            if isinstance(value, dict):
                out |= paths(value, f"{prefix}{key}.")
            else:
                out.add(prefix + key)
        return out

    missing = paths(identity) - paths(other)
    assert not missing, f"{theme} publishes none of: {sorted(missing)}"


def declared_radius(css: str, class_name: str) -> str | None:
    """The `border-radius` the first plain rule for `class_name` paints.

    Split on commas and take each selector's last token, because the landing heads a rule with a
    section comment -- `/* buttons */ .btn-primary, .btn-secondary` -- and a state rule
    (`.btn-primary:hover`) is not the resting corner the buyer and the user both see.
    """
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css, re.S):
        names = {part.split()[-1] for part in selector.split(",") if part.split()}
        if class_name not in names:
            continue
        value = re.search(r"border-radius:\s*([^;]+)", body)
        if value:
            return value.group(1).strip()
    return None


def radius_px(declaration: str | None) -> float | None:
    """Any radius spelling reduced to pixels, token reference resolved through the token file."""
    if declaration is None:
        return None
    text = declaration.strip()
    reference = re.fullmatch(r"var\(--dt-border-radius-([a-z0-9-]+)\)", text)
    if reference:
        text = token_at(app_tokens(), f"border-radius.{reference.group(1)}")
        assert isinstance(text, str)
    number = re.fullmatch(r"([0-9.]+)(px|rem)", text)
    if number is None:
        return None
    value = float(number.group(1))
    return value * 16 if number.group(2) == "rem" else value


def test_the_two_surfaces_round_their_primary_button_the_same_way() -> None:
    """`.btn-primary` exists in both sheets, so it is one control the buyer and the user meet twice.

    The repaint put every utility onto the token ladder but left the SPA's hand-written rules alone,
    and the button among them carried 10px while the landing's carries 4px -- the same word rendered
    with two different corners, which is the whole defect this file was written to catch.
    """
    site = radius_px(declared_radius(SITE_CSS.read_text(encoding="utf-8"), ".btn-primary"))
    app = radius_px(declared_radius((STYLES / "index.css").read_text(encoding="utf-8"), ".btn-primary"))
    assert site is not None and app is not None, "one of the two sheets stopped naming .btn-primary"
    assert site == app, f"the storefront rounds its primary button to {site}px, the app to {app}px"


def test_the_button_radius_reader_resolves_the_token_and_ignores_the_state_rule() -> None:
    sheet = (STYLES / "index.css").read_text(encoding="utf-8")
    assert radius_px(declared_radius(sheet, ".btn-primary")) == 4.0, "the control step the landing uses"
    assert radius_px("0.625rem") == 10.0, "the number the button carried before the fix"
    assert radius_px("var(--dt-border-radius-full)") == 9999.0, "a pill resolves like any other step"
    assert (
        declared_radius(".btn-primary:hover { border-radius: 0; } .btn-primary { border-radius: 4px; }", ".btn-primary")
        == "4px"
    )


# ---------------------------------------------------------------------------------------------
# A surface that names a brand face in a font stack has to carry that face in its own document.
# ---------------------------------------------------------------------------------------------


def _generator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_theme_css", ROOT / "scripts" / "gen_theme_css.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VENDORED_FONTS = ROOT / "web" / "public" / "fonts"

#: Each surface with the prefix its document resolves a font URL against: the gateway pages are served
#: from the origin, so `/fonts/` lands in `web/dist/fonts`; the popup is a file inside an MV3 package
#: whose only document is `src/popup/index.html`, so its copies travel with it; the VS Code webview reads
#: only URIs the extension host prints for a granted directory, so its region is written against the
#: `${fontRoot}` placeholder the panel interpolates.
FONTED_SURFACES: tuple[tuple[str, Path, str], ...] = (
    ("the gateway's webchat page", ROOT / "raven" / "channels" / "webchat" / "channel.py", "/fonts/"),
    ("the offline shell", ROOT / "web" / "public" / "offline.html", "/fonts/"),
    ("the MV3 popup", ROOT / "extension" / "src" / "popup" / "popup.css", "fonts/"),
    ("the VS Code chat panel", ROOT / "extension" / "vscode" / "src" / "panel.ts", "${fontRoot}/"),
)

# `[^}]*` is the shape a face block does not have: the VS Code panel's URLs carry the `${fontRoot}`
# placeholder its host interpolates, and a reader that stopped at the first closing brace would cut that
# block in half, report no `src` at all, and call the face delivered. A printed face block closes on its
# own line, so the reader anchors there.
_FACE_BLOCK = re.compile(r"@font-face\s*\{.*?\n\s*\}", re.S)
_FACE_FAMILY = re.compile(r"font-family\s*:\s*([^;]+);")
_FACE_URL = re.compile(r"url\(['\"]?([^'\")]+)['\"]?\)")
_STACK_DECL = re.compile(r"(?<![-\w])font-family\s*:\s*([^;{}]+);")
# Any custom property, not only one whose name says `font-family`: a surface is free to call its stack
# `--font-body`, and a guard that reads only the named ones resolves `var(--font-body)` to nothing.
_TOKEN_DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+);")


def brand_families() -> set[str]:
    """The families the product owns, read from the design tokens rather than written into a test."""
    tokens = app_tokens()
    return {first_family(token_at(tokens, f"typography.font-family.{role}")) for role in ("sans", "mono", "display")}


def face_dir(prefix: str) -> Path:
    """The directory a surface's font URLs land in."""
    if prefix == "/fonts/":
        return VENDORED_FONTS
    if prefix == "fonts/":
        return ROOT / "extension" / "src" / "popup" / "fonts"
    if prefix == "${fontRoot}/":
        return ROOT / "extension" / "vscode" / "assets" / "fonts"
    raise AssertionError(f"no surface is known that resolves fonts against {prefix!r}")


def face_path(prefix: str, url: str) -> Path:
    """Where a browser asking for `url` ends up, inside this repository."""
    return face_dir(prefix) / url.rsplit("/", 1)[-1]


def undelivered_faces(text: str, prefix: str) -> list[str]:
    """Every way this document fails to give a reader the type it promises.

    The families a document *paints with* are what its stacks lead with, including the ones a token
    line leads with and the ones a rule reaches through `var()` — a rule that says
    `var(--dt-typography-font-family-sans)` is the browser's answer to which file it will fetch, so
    reading only literal family names would let this guard pass on a page that had none.
    """
    owned = brand_families()
    props = {name: value for name, value in _TOKEN_DECL.findall(text)}
    named: set[str] = set()
    for decl in _STACK_DECL.findall(text) + list(props.values()):
        lead = decl.split(",")[0].strip()
        if lead.startswith("var("):
            lead = props.get(lead[4:-1].strip(), "").split(",")[0].strip()
        family = first_family(lead) if lead else ""
        if family in owned:
            named.add(family)

    delivered: dict[str, list[str]] = {}
    for block in _FACE_BLOCK.findall(text):
        if fam := _FACE_FAMILY.search(block):
            delivered.setdefault(first_family(fam.group(1)), []).extend(u for u in _FACE_URL.findall(block))

    offenders = [
        f"leads a font stack with {family!r} and declares no @font-face for it — that text renders in "
        f"the reader's system font"
        for family in sorted(named - set(delivered))
    ]
    offenders += [
        f"declares a face for {family!r} whose src this guard cannot read, so nothing below can prove the file arrives"
        for family in sorted(f for f in named & set(delivered) if not delivered[f])
    ]
    for family in sorted(named & set(delivered)):
        for url in delivered[family]:
            path = face_path(prefix, url)
            if not path.is_file():
                offenders.append(f"{family!r} asks for {url!r} which resolves to {path}, and it is not there")
                continue
            if path.read_bytes()[:4] != b"wOF2":
                offenders.append(f"{path.name} is not a woff2 file")
            vendored = VENDORED_FONTS / path.name
            if path != vendored and path.read_bytes() != vendored.read_bytes():
                offenders.append(f"{path.relative_to(ROOT)} is a different font than {vendored.relative_to(ROOT)}")
    return offenders


def test_every_surface_that_leads_a_brand_stack_delivers_the_faces() -> None:
    """The landing's typography reached the SPA and stopped there.

    Before this ran, the webchat page and the MV3 popup both led their stacks with `"IBM Plex Sans"` and
    `"IBM Plex Mono"` and shipped zero `@font-face` rules, so the gateway's own chat and the browser
    panel set the brand typefaces in a document that could not fetch them — a silent fall through to
    system-ui on every machine, while `vite dev` looked right because it serves `web/public/` itself.
    `web/public/offline.html` was worse still: it named `-apple-system, … Roboto` and never mentioned
    the brand at all. The VS Code panel is here on the same terms as the others, for the text it owns:
    its name and its status pill lead with the brand and now deliver the files, while the conversation
    leads with `--vscode-font-family` and `--vscode-editor-font-family` and falls through to the brand
    only where no VS Code variable exists — a webview that overrode the type the reader picked for their
    own editor would be wrong in the other direction, and this guard reads only the stacks a document
    actually leads with the brand.
    """
    for label, path, prefix in FONTED_SURFACES:
        offenders = undelivered_faces(path.read_text(encoding="utf-8"), prefix)
        assert not offenders, f"{label} ({path.relative_to(ROOT)}):\n" + "\n".join(offenders)


def test_the_face_guard_notices_a_surface_that_stops_delivering() -> None:
    """A guard that only ever reads green is a guard nobody tested.

    The sample is written here rather than read from the tree so the proofs hold whatever the real
    surfaces do next: the same mutation has to be caught whether the popup ships its fonts today or
    ships them in a year.
    """
    sample = """
        :root {
          --dt-typography-font-family-sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
          --dt-typography-font-family-mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", monospace;
        }
        @font-face {
          font-family: 'IBM Plex Sans';
          src: url('fonts/IBMPlexSans-notvendored.woff2') format('woff2');
        }
        body { font-family: var(--dt-typography-font-family-sans); }
        code { font-family: var(--dt-typography-font-family-mono); }
        """

    offenders = undelivered_faces(sample, "/fonts/")
    assert any("ibm plex mono" in o for o in offenders), "a stack reaching the brand through var() read as no stack"
    assert any("not there" in o for o in offenders), "a face whose file the package does not hold passed as delivered"

    assert any("ibm plex sans" in o for o in undelivered_faces(_FACE_BLOCK.sub("", sample), "/fonts/")), (
        "deleting every @font-face left the surface looking clean"
    )
    assert any(
        "ibm plex sans" in o
        for o in undelivered_faces(
            sample.replace("var(--dt-typography-font-family-sans)", '"IBM Plex Sans", sans-serif'), "/fonts/"
        )
    ), "a literal brand stack was read differently from the var() one it resolves to"
    unbranded = sample.replace("IBM Plex Sans", "Inter").replace("IBM Plex Mono", "Inter")
    assert not undelivered_faces(unbranded, "/fonts/"), (
        "the guard polices the brand families, and must not fail a page for a font it never promised"
    )

    # A face block whose `src` the reader cannot parse has to be an offender rather than a clean sheet:
    # half-closed, the block reads as declaring the family with nothing to check, which is the way this
    # guard once passed on the VS Code panel.
    unreadable = sample.replace("url('fonts/IBMPlexSans-notvendored.woff2')", "url(fonts/IBMPlexSans.woff2")
    assert any("cannot read" in o for o in undelivered_faces(unreadable, "/fonts/")), (
        "a face whose src was not parsed counted as delivered"
    )

    # And a placeholder URL — the webview's form, where the host interpolates the root at runtime — has
    # to be resolved to the file it names, not waved through.
    placeholdered = sample.replace("fonts/IBMPlexSans-notvendored.woff2", "${fontRoot}/IBMPlexSans-nope.woff2")
    assert any("nope" in o for o in undelivered_faces(placeholdered, "${fontRoot}/")), (
        "a placeholder face URL was read as no URL at all"
    )


def test_the_packages_ship_exactly_the_faces_their_sheets_ask_for() -> None:
    """Orphans are bytes in a zip, and missing ones are a font that never arrives.

    Only the two surfaces that are packages: the gateway's pages and the offline shell read
    `web/dist/fonts`, which a build produces rather than a list someone maintains.
    """
    packages = [(label, path, prefix) for label, path, prefix in FONTED_SURFACES if prefix != "/fonts/"]
    assert len(packages) >= 2, f"the guard reads {packages}, and a single package proves nothing about a second"
    for label, sheet, prefix in packages:
        text = sheet.read_text(encoding="utf-8")
        asked = {face_path(prefix, url).name for block in _FACE_BLOCK.findall(text) for url in _FACE_URL.findall(block)}
        shipped = {p.name for p in face_dir(prefix).glob("*.woff2")}
        assert asked, f"{label} declares no face to ship, so the comparison below has nothing to compare"
        assert asked == shipped, f"{label} asks for {sorted(asked - shipped)} and ships {sorted(shipped - asked)}"


def test_the_face_regions_are_what_the_generator_prints() -> None:
    """A copied region is only true until someone edits `fonts.css` and forgets to regenerate.

    The host list is the generator's own registration, so a surface registered there is policed here
    without anyone remembering to name it twice: the webchat page, the offline shell and the MV3 popup
    take their faces with their own URL prefix, the VS Code panel takes them against the placeholder its
    host interpolates, and the worker takes the file list with the gateway prefix. Each document holds
    the printed result, so this compares the copy with what the generator emits now, byte for byte.
    """
    gen = _generator()
    for command, hosts in gen.FONT_REGION_HOSTS.items():
        block = gen.font_region(command)
        start, _end = gen._font_sentinels(command.rsplit(" ", 1)[-1])
        for rel in hosts:
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert block in text, f"{rel} embeds a face region that does not match web/src/styles/fonts.css"
            assert text.count(start) == 1, f"{rel} holds the {command} region more than once"


def test_no_document_pastes_faces_the_registration_does_not_cover(tmp_path: Path) -> None:
    """A surface that hands out faces by hand is invisible to the guard above, which is how a fifth
    document would ship type nobody compares with the bundle."""
    gen = _generator()
    heads = [gen._font_sentinels(target)[0] for target in (*gen.FONT_PREFIXES, "precache")]
    roots = tuple(ROOT / name for name in _REGION_SCAN_ROOTS)
    registered = {ROOT / rel for hosts in gen.FONT_REGION_HOSTS.values() for rel in hosts}

    scanned = documents_pasting_a_region(gen, roots, heads)
    assert scanned, "the sweep reads nothing, which is how a gate like this passes by accident"
    assert scanned == registered, (
        f"unregistered face regions: {sorted(p.relative_to(ROOT) for p in scanned - registered)}"
    )

    stray = tmp_path / "stray.css"
    stray.write_text(f":root {{\n{gen.font_block('gateway')}\n}}\n", encoding="utf-8")
    assert documents_pasting_a_region(gen, (tmp_path,), heads) == {stray}, "a pasted face region escaped the sweep"
    assert documents_pasting_a_region(gen, (tmp_path,), [gen._surface_sentinels("--print-surface")[0]]) == set(), (
        "the face markers were read as a palette region, so the two sweeps are not the same question"
    )


# ---------------------------------------------------------------------------------------------
# The scaffold generator: a project the gateway hands back is a surface of this product too, and the
# only reader it gets is the one below.
#
# `raven/core/scaffold_api.py` used to emit a React starter whose only colour was
# `style={{ backgroundColor: "#0a0a0a", color: "#e4e4e7" }}` with `text-zinc-400` and `bg-indigo-600`
# on the button: the storefront's palette is #0a0812/#8452f5, so a generated app looked like a different
# company's product, and `indigo-600` is the one Tailwind default the design contract retires. The
# starter now carries the same generated region the offline surfaces embed, and these guards compare it
# with what the generator prints rather than with a remembered hex.
# ---------------------------------------------------------------------------------------------

_SCAFFOLD_REGION = re.compile(r"/\* design-tokens:start.*?:end \*/", re.S)
_DT_USE = re.compile(r"var\((--dt-[\w-]+)\)")
_DT_DECL = re.compile(r"(--dt-[\w-]+):")
_HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")

_SCAFFOLD_COMBOS: tuple[tuple[str, str, dict[str, object]], ...] = (
    ("ts-react, router and zustand", "ts-react", {"use_router": True, "use_state": "zustand"}),
    ("ts-react, no router, no store", "ts-react", {"use_router": False, "use_state": "none"}),
    ("fastapi-react, auth and docker", "fastapi-react", {"use_auth": True, "use_db": "sqlite", "use_docker": True}),
)


def _generated_project(template_id: str, extra: dict[str, object]) -> dict[str, str]:
    from raven.core.scaffold_api import _gen_fastapi_react, _gen_ts_react

    generator = {"ts-react": _gen_ts_react, "fastapi-react": _gen_fastapi_react}[template_id]
    answers: dict[str, object] = {"project_name": "brand-check", **extra}
    return {item["path"]: item["content"] for item in generator(answers)}


def test_a_generated_project_paints_with_the_scale_the_product_ships() -> None:
    """The starter's stylesheet has to hold the region the generator prints, and nothing else of its own."""
    region = _generator().scaffold_block()
    for label, template_id, extra in _SCAFFOLD_COMBOS:
        project = _generated_project(template_id, extra)
        css = next(content for path, content in project.items() if path.endswith("src/index.css"))
        assert css.count(region) == 1, f"{label}: the emitted stylesheet does not hold the printed region once"

        asked = set(_DT_USE.findall("".join(project.values())))
        declared = set(_DT_DECL.findall(region))
        assert asked, f"{label}: nothing in the generated project uses the scale, so the comparison is vacuous"
        assert asked <= declared, f"{label} asks for {sorted(asked - declared)}, which tokens.json does not publish"

        for path, content in project.items():
            naked = _HEX_LITERAL.findall(_SCAFFOLD_REGION.sub("", content))
            assert not naked, f"{label}: {path} carries a colour of its own: {naked}"


def test_a_generated_project_promises_no_face_it_cannot_deliver() -> None:
    """A scaffold is text over HTTP, so it ships no woff2 and must not name a brand family.

    The starter leads its stacks with `ui-sans-serif`/`ui-monospace`, which is what the brand families
    fall through to when the files are absent -- honest in the one place the product cannot deliver type.
    """
    for label, template_id, extra in _SCAFFOLD_COMBOS:
        project = _generated_project(template_id, extra)
        for path, content in project.items():
            if path.endswith((".css", ".html", ".tsx")):
                offenders = undelivered_faces(content, "/fonts/")
                assert not offenders, f"{label}: {path}" + "\n" + "\n".join(offenders)


def _mutate(text: str, old: str, new: str) -> str:
    """Plant a violation, refusing to let a proof run on a mutation that no longer lands.

    A guard was once shown to catch a hand-edited accent by replacing text the emitted file did not
    contain: the assert passed, the guard was blind, and nothing said so.
    """
    assert old in text, f"the planted violation rewrites {old!r}, which the emitted file does not contain"
    return text.replace(old, new)


def test_the_scaffold_guards_notice_a_starter_that_drifts() -> None:
    """Green once is not green forever: each mutation is the mistake a later edit could make."""
    region = _generator().scaffold_block()
    css = _generated_project("ts-react", {"use_router": False, "use_state": "none"})["src/index.css"]

    hand_edited = _mutate(css, "#8452f5", "#7c3aed")
    assert hand_edited.count(region) == 0, "an accent changed by hand still read as the printed region"

    private = _mutate(css, "var(--dt-colors-accent-default)", "#0a0a0a")
    assert _HEX_LITERAL.findall(_SCAFFOLD_REGION.sub("", private)), "a colour literal outside the region went unseen"

    assert region in css, "the emitted stylesheet never held the region, so dropping it proves nothing"
    unused_scale = css.replace(region, "")
    assert not _DT_DECL.findall(unused_scale), "the region was found somewhere other than where it is declared"

    promised = undelivered_faces(
        _mutate(css, "--font-body: ui-sans-serif", '--font-body: "IBM Plex Sans", ui-sans-serif'), "/fonts/"
    )
    assert promised, "naming a brand family without shipping the file read as delivered"


# ---------------------------------------------------------------------------------------------
# A mark is drawn. A text glyph is a request to whatever typeface the reader happens to hold.
# ---------------------------------------------------------------------------------------------

#: The Unicode blocks that hold pictures instead of letters. A surface that states its condition with
#: one of these hands the decision to the reader's font: whether the codepoint has a face at all, how
#: big it is next to the type around it, where it sits on the baseline, and whether `color:` reaches
#: it. A drawn shape answers all four the way the stylesheet says.
_PICTURE_BANDS: tuple[tuple[int, int], ...] = (
    (0x25A0, 0x25FF),
    (0x2600, 0x27BF),
    (0x2800, 0x28FF),
    (0x1F000, 0x1FAFF),
)

#: Source that reaches a screen. The chat platforms and the terminal are absent on purpose: a Telegram
#: reply is drawn by Telegram in another medium, and several suites assert the emoji it carries, so
#: forbidding them there would forbid the product's own words.
_SURFACES: tuple[tuple[Path, tuple[str, ...]], ...] = (
    (ROOT / "web" / "src", (".tsx", ".ts", ".css")),
    (ROOT / "web" / "public", (".html", ".css", ".js", ".svg")),
    (ROOT / "extension" / "src", (".html", ".css", ".js", ".svg")),
    (ROOT / "extension" / "vscode" / "src", (".ts",)),
    (ROOT / "site", (".html", ".css", ".js", ".svg")),
)

#: Python documents that ship markup to a browser.
_INLINE_MARKUP = (
    ROOT / "raven" / "channels" / "webchat" / "channel.py",
    ROOT / "raven" / "core" / "workflow" / "templates.py",
)


def rendered_surfaces() -> list[Path]:
    """Every shipped file whose bytes a browser or a webview paints."""
    files = [
        path
        for base, suffixes in _SURFACES
        for path in sorted(base.rglob("*"))
        if path.is_file() and path.suffix in suffixes and "node_modules" not in path.parts
    ]
    files += [ROOT / "web" / "index.html", *_INLINE_MARKUP]
    # A test source is not a surface: the collaborative editor's fixtures carry astral characters
    # because a surrogate pair is exactly what that code has to survive, and none of it is painted.
    return [path for path in files if path.is_file() and ".test." not in path.name]


def pictures(text: str) -> list[str]:
    """Each pictograph in a document, as `U+XXXX on line n`.

    Read line by line after HTML unescaping, because the browser paints the entity, not the bytes: the SPA
    shell carried its favicon as `&#x1F426;` and passed this sweep for as long as the sweep looked for a raw
    codepoint. Line numbers stay the source's own, since a character reference does not span a newline.
    """
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for char in unescape(line):
            if any(low <= ord(char) <= high for low, high in _PICTURE_BANDS):
                found.append(f"U+{ord(char):04X} on line {number}")
    return found


def test_nothing_a_browser_paints_states_itself_with_a_font_glyph() -> None:
    """The console led with a filled dot, a tick, a warning, a star, a spinner and a bird emoji -- green.

    Those characters are what an operator reads as the product's state. Each one renders from whatever
    the reader's system font holds, so the same row is a dot on one machine and a hollow box on
    another, at a size the layout cannot set and in a colour the theme cannot move. Every one is now a
    drawn mark: lucide in the SPA, a CSS circle in the popup, the vector bird for the brand.
    """
    scanned = rendered_surfaces()
    for base, _suffixes in _SURFACES:
        assert sum(1 for path in scanned if path.is_relative_to(base)) > 3, (
            f"{base.relative_to(ROOT)} is no longer represented, so the sweep does not cover it"
        )
    assert ROOT / "web" / "index.html" in scanned, "the SPA shell left the swept set"
    assert all(path in scanned for path in _INLINE_MARKUP), "a page shipped from Python left the swept set"
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {hit}"
        for path in scanned
        for hit in pictures(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, "these paint a picture with a text glyph:\n" + "\n".join(offenders)


def test_the_pictograph_sweep_sees_every_block_it_claims_to() -> None:
    """One band that matches nothing is a guard that quietly stopped existing.

    A colour scanner in this file carried a literal backspace where it meant a word boundary, and both
    its assertion and its own planted violation passed for a whole wave because neither could match.
    """
    for sample in ("\u25a0", "\u2713", "\u28bf", "\U0001f426"):
        found = pictures(f'<span aria-label="state">{sample}</span>')
        assert found == [f"U+{ord(sample):04X} on line 1"], f"the sweep is blind to U+{ord(sample):04X}"
    assert pictures("<kbd>Cmd</kbd> ready \u2192 \u2318 \u2014") == [], "the sweep forbids ordinary typography too"


# ---------------------------------------------------------------------------------------------
# One bird, drawn once, at every size the product ships.
# ---------------------------------------------------------------------------------------------

_MARK_VECTORS: tuple[tuple[str, Path], ...] = (
    ("the tab icon the landing ships", ROOT / "site" / "favicon.svg"),
    ("the tab icon the app ships", ROOT / "web" / "public" / "favicon.svg"),
    ("the mark in the MV3 popup header", ROOT / "extension" / "src" / "popup" / "raven.svg"),
    ("the installable app's 192 icon", ROOT / "web" / "public" / "icons" / "icon-192.svg"),
    ("the installable app's 512 icon", ROOT / "web" / "public" / "icons" / "icon-512.svg"),
)

#: Documents that draw the mark inside their own markup instead of linking a file.
_INLINED_MARKS: tuple[tuple[str, Path], ...] = (
    ("the VS Code chat panel", ROOT / "extension" / "vscode" / "src" / "panel.ts"),
)

#: The command that re-renders each family of shipped icons. Naming it in the failure is what makes a
#: stale asset actionable: two generators own these files and neither knows about the other's output.
RERENDER_ICONS = "python scripts/make_extension_icons.py --force"
RERENDER_WEB_ICONS = "python scripts/make_web_icons.py"

#: Rasters the shipped packages carry, each with the generator that owns it. These were drawn by hand in
#: `scripts/icon_render.py` from another bird entirely -- a white body on a violet gradient -- so the
#: product wore one face on the site and a different one in the toolbar, the marketplace tile and the
#: Windows taskbar.
_SHIPPED_RASTERS: tuple[tuple[str, Path, int, str], ...] = (
    ("the browser toolbar icon", ROOT / "extension" / "icons" / "icon16.png", 16, RERENDER_ICONS),
    ("the browser taskbar icon", ROOT / "extension" / "icons" / "icon48.png", 48, RERENDER_ICONS),
    ("the browser listing icon", ROOT / "extension" / "icons" / "icon128.png", 128, RERENDER_ICONS),
    ("the VS Code marketplace icon", ROOT / "extension" / "vscode" / "icon.png", 256, RERENDER_ICONS),
    ("the app's install tile", ROOT / "web" / "public" / "icons" / "icon-192.png", 192, RERENDER_WEB_ICONS),
    ("the app's large install tile", ROOT / "web" / "public" / "icons" / "icon-512.png", 512, RERENDER_WEB_ICONS),
)

#: The Windows icon files, each with the frame this comparison reads and the command that regenerates it.
#: A browser asks an install for `/favicon.ico` whether or not a document linked it, so a stale frame here
#: is a taskbar button wearing a mark no source file holds any more.
_SHIPPED_ICOS: tuple[tuple[str, Path, int, str], ...] = (
    ("the executable's icon", ROOT / "scripts" / "raven.ico", 256, "python scripts/make_icon.py"),
    ("the app's favicon", ROOT / "web" / "public" / "favicon.ico", 48, RERENDER_WEB_ICONS),
)

_SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.S)
_TEMPLATE_ICON = re.compile(r'\bicon="([a-z0-9][a-z0-9-]*)"')
_ICON_TABLE = re.compile(r"const TEMPLATE_ICONS[^{]*\{(.*?)\n\};", re.S)
_ICON_KEY = re.compile(r'^\s*"?([a-z0-9-]+)"?:\s*[A-Z]\w*', re.M)


def _mark_writer():
    import importlib.util

    spec = importlib.util.spec_from_file_location("icon_render", ROOT / "scripts" / "icon_render.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mark_signature(svg_text: str) -> tuple[Any, ...] | None:
    """The drawing a vector makes, in fractions of its own tile, or nothing if it is not a tile.

    Normalising by the viewBox is what lets a 32-unit favicon and a 512-unit app icon be the same
    mark; a signature taken from raw coordinates would call the larger copy a different bird.
    """
    writer = _mark_writer()
    try:
        side = writer.canvas_size(svg_text)
        shapes = tuple(
            (tuple((round(x / side, 4), round(y / side, 4)) for x, y in vertices), colour)
            for vertices, colour in writer.mark_shapes(svg_text)
        )
        plate_colour, radius = writer.plate(svg_text)
    except ValueError:
        return None
    return (plate_colour, round(radius / side, 4), shapes)


def the_mark() -> tuple[Any, ...]:
    signature = mark_signature((ROOT / "site" / "favicon.svg").read_text(encoding="utf-8"))
    assert signature is not None, "site/favicon.svg does not draw a mark this repository can read"
    return signature


def test_every_copy_of_the_brand_mark_draws_the_same_bird() -> None:
    """Four files carry the brand; before this ran, two of them carried an emoji set in a font."""
    original = the_mark()
    for label, path in _MARK_VECTORS:
        assert path.is_file(), f"{label} ({path.relative_to(ROOT)}) is not in the package"
        assert mark_signature(path.read_text(encoding="utf-8")) == original, (
            f"{label} is a different drawing than site/favicon.svg"
        )


def test_a_document_that_inlines_the_mark_inlines_this_one() -> None:
    for label, path in _INLINED_MARKS:
        blocks = _SVG_BLOCK.findall(path.read_text(encoding="utf-8"))
        assert blocks, f"{label} no longer draws a mark of its own, and nothing replaced it"
        signatures = [mark_signature(block) for block in blocks]
        assert the_mark() in signatures, f"{label} inlines a mark that is not the one the site ships"


def test_the_shipped_rasters_are_the_vector_at_the_size_the_manifest_declares() -> None:
    from PIL import Image

    writer = _mark_writer()
    for label, path, size, regenerate in _SHIPPED_RASTERS:
        assert path.is_file(), f"{label} ({path.relative_to(ROOT)}) is missing"
        shipped = Image.open(path)
        assert shipped.size == (size, size), f"{label} is {shipped.size[0]}x{shipped.size[1]}, not {size}"
        painted = writer.render_icon(size).convert("RGBA")
        assert shipped.convert("RGBA").tobytes() == painted.tobytes(), (
            f"{label} is not the current mark rendered -- run {regenerate}"
        )


def test_the_windows_icons_hold_the_same_bird_as_the_pngs() -> None:
    """Each `.ico` is read at the frame a browser asks an install for, not at the frame that is easiest.

    An ICO carries several renders of one image, and Windows paints the largest the surface wants while a
    tab asks for 16 or 32. The comparison is made on the frame the generator renders natively, because
    `PIL` derives the rest by resampling it: the smaller frames are therefore the same drawing rescaled,
    which is what the site asks for, but their bytes come from `PIL`'s filter rather than from
    `icon_render`, so a claim about them here would be a claim about the library.
    """
    from PIL import IcoImagePlugin, Image

    for label, icon, size, regenerate in _SHIPPED_ICOS:
        assert icon.is_file(), f"{icon.relative_to(ROOT)} is what {label} is stamped with"
        handle = cast("IcoImagePlugin.IcoImageFile", Image.open(icon))
        frames = handle.ico.sizes()
        assert (size, size) in frames and (16, 16) in frames, f"{label} frames: {sorted(frames)}"
        painted = _mark_writer().render_icon(size).convert("RGBA")
        frame = handle.ico.getimage((size, size)).convert("RGBA")
        assert frame.tobytes() == painted.tobytes(), f"{label} is not the current mark -- run {regenerate}"


def _template_marks() -> tuple[set[str], set[str]]:
    asked = set(
        _TEMPLATE_ICON.findall((ROOT / "raven" / "core" / "workflow" / "templates.py").read_text(encoding="utf-8"))
    )
    table = _ICON_TABLE.search((ROOT / "web" / "src" / "pages" / "Workflows.tsx").read_text(encoding="utf-8"))
    assert table is not None, "Workflows.tsx no longer holds a TEMPLATE_ICONS table to compare against"
    return asked, set(_ICON_KEY.findall(table.group(1)))


def test_every_mark_a_template_asks_for_is_one_the_console_can_draw() -> None:
    """The gallery is React, the seed list is Python, and neither import can see the other.

    An unknown name is not an error at the seam -- it falls back to a generic mark -- so a rename turns
    the first screen a customer meets into a wall of identical marks without failing a build.
    """
    asked, drawn = _template_marks()
    assert len(asked) > 8, f"only {len(asked)} templates declare a mark, so this comparison is thin"
    assert len(drawn) > 8, f"the console knows {len(drawn)} marks, which is not the gallery's vocabulary"
    unknown = sorted(asked - drawn)
    assert not unknown, f"templates ask for marks the console cannot draw: {unknown}"


def test_a_group_inside_a_group_moves_the_mark_the_way_a_browser_moves_it() -> None:
    """`scale(2)` around `translate(4 4)` puts a point at `2 * (p + 4)`, not at `2 * p + 4`.

    The renderer collected the enclosing groups in document order and composed each one as though it were
    the innermost, which is invisible while every shipped vector holds its drawing in one group -- and is
    four units of the tile off the mark the site shows as soon as one vector is generated by wrapping the
    original group in a scale, which is exactly what `scripts/make_web_icons.py` emits.
    """
    nested = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="4" fill="#0a0812"/>'
        '<g transform="scale(2)"><g transform="translate(4 4)">'
        '<path d="M2 2 10 2 10 10Z" fill="#8b5cf6"/>'
        "</g></g></svg>"
    )
    shapes = _mark_writer().mark_shapes(nested)
    assert len(shapes) == 1, f"the probe drew {len(shapes)} shapes, not the one it declares"
    assert shapes[0][0] == [(12.0, 12.0), (28.0, 12.0), (28.0, 28.0)], "a nested group moved the mark inside-out"


def test_the_mark_guards_notice_a_copy_that_drifts() -> None:
    """Each mutation is a mistake a later edit can actually make."""
    from PIL import Image

    writer = _mark_writer()
    favicon = (ROOT / "site" / "favicon.svg").read_text(encoding="utf-8")
    original = the_mark()

    recoloured = mark_signature(_mutate(favicon, 'fill="#d946ef"', 'fill="#ff0055"'))
    assert recoloured != original, "a wing repainted by hand still signed as the shipped mark"

    reshaped = mark_signature(_mutate(favicon, "M12 2 3 12", "M12 2 4 12"))
    assert reshaped != original, "a vertex moved by hand still signed as the shipped mark"

    assert mark_signature(_mutate(favicon, 'viewBox="0 0 32 32"', 'viewBox="0 0 40 32"')) is None, (
        "a tile that is no longer square was rasterised anyway"
    )
    assert mark_signature(_mutate(favicon, "M12 2 3 12l9 10", "M12 2 C3 12 9 10 4 4")) is None, (
        "a curve was flattened into a chord instead of refused"
    )

    swapped = writer.render_icon(128, _mutate(favicon, 'fill="#8b5cf6"', 'fill="#7c3aed"'))
    shipped = Image.open(ROOT / "extension" / "icons" / "icon128.png").convert("RGBA")
    assert swapped.tobytes() != shipped.tobytes(), "the raster comparison cannot tell one accent from another"
    mirrored = shipped.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    assert mirrored.tobytes() != shipped.tobytes(), "the mark is symmetric, so a flipped icon would pass unseen"

    templates = (ROOT / "raven" / "core" / "workflow" / "templates.py").read_text(encoding="utf-8")
    _, drawn = _template_marks()
    renamed = set(_TEMPLATE_ICON.findall(_mutate(templates, 'icon="sunrise"', 'icon="sunset"')))
    assert "sunset" in renamed - drawn, "a template renamed to a mark the console lacks went unseen"


# --- what a browser is asked to execute ---

_ENGINE_COMPILER = """
import vm from "node:vm";
import { readFileSync } from "node:fs";
const manifest = JSON.parse(readFileSync(process.argv[2], "utf8"));
let bad = 0;
for (const item of manifest) {
  const text = readFileSync(item.path, "utf8");
  try {
    if (item.kind === "module") {
      new vm.SourceTextModule(text, { identifier: item.label });
    } else {
      new vm.Script(text, { filename: item.label });
    }
  } catch (err) {
    bad++;
    console.log(item.label + " :: " + String(err.message).split("\\n")[0]);
  }
}
console.log("compiled " + (manifest.length - bad) + "/" + manifest.length);
"""

_SCRIPT_TAG = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.S)
_SCRIPT_ATTR = re.compile(r"([\w-]+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?")
_MODULE_PATH = re.compile(r"(?:\bfrom|\bimport)\s*['\"](\.[^'\"]*|/[^'\"]*)['\"]")


def tag_attributes(raw: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _SCRIPT_ATTR.finditer(raw):
        found[match.group(1).lower()] = match.group(2) or match.group(3) or match.group(4) or ""
    return found


def shipped_sheets() -> dict[Path, str]:
    """The documents that never load the SPA bundle, as the reader gets them."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from raven.channels.webchat.channel import WebChatChannel
    from raven.core.db import Database

    # The document is built before any request touches the handle, so the database this channel never uses
    # stays a placeholder -- and the type says so instead of the test claiming the constructor takes anything.
    gateway_page = TestClient(WebChatChannel(cast("Database", SimpleNamespace())).app).get("/")
    sheets = {
        ROOT / "web" / "public" / "offline.html": (ROOT / "web" / "public" / "offline.html").read_text(
            encoding="utf-8"
        ),
        ROOT / "extension" / "src" / "popup" / "index.html": (
            ROOT / "extension" / "src" / "popup" / "index.html"
        ).read_text(encoding="utf-8"),
        ROOT / "gateway" / "webchat": gateway_page.text,
    }
    for page in sorted((ROOT / "site").glob("*.html")):
        sheets[page] = page.read_text(encoding="utf-8")
    return sheets


def document_scripts(sheets: dict[Path, str]) -> tuple[list[dict[str, str]], list[str]]:
    """The blocks a browser is told to run, followed through the module graph, and what it cannot get.

    The gateway's own page reaches the SPA bundle through a hashed `/assets/` name the frontend build writes
    and `tsc`/vitest gate, so that reference is left to them; every other one has to be a file.
    """
    blocks: list[dict[str, str]] = []
    refused: list[str] = []
    queued: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    for sheet, html in sheets.items():
        for index, (raw_attrs, body) in enumerate(_SCRIPT_TAG.findall(html)):
            attrs = tag_attributes(raw_attrs)
            kind = (attrs.get("type") or "classic").lower()
            source = attrs.get("src", "")
            if source.startswith(("http://", "https://", "//", "data:")):
                refused.append(f"{sheet.name}: reaches off-origin for {source}")
                continue
            if source.startswith("/assets/"):
                continue
            if kind == "application/ld+json":
                try:
                    json.loads(body)
                except ValueError as err:
                    refused.append(f"{sheet.name}: its ld+json block is not JSON ({err})")
                continue
            if source:
                target = ROOT / source.lstrip("/") if source.startswith("/") else sheet.parent / source
                if not target.is_file():
                    refused.append(f"{sheet.name}: names {source}, which does not ship")
                    continue
                text = target.read_text(encoding="utf-8")
                origin, label = target, str(target.relative_to(ROOT))
            else:
                text, origin, label = body, sheet, f"{sheet.name} inline #{index}"
            if label in seen:
                continue
            seen.add(label)
            blocks.append({"label": label, "text": text, "kind": kind})
            queued.append((origin, text, kind))
    while queued:
        origin, text, kind = queued.pop()
        if kind != "module":
            continue
        for import_path in _MODULE_PATH.findall(text):
            target = ROOT / import_path.lstrip("/") if import_path.startswith("/") else origin.parent / import_path
            if not target.is_file():
                refused.append(f"{origin.name}: imports {import_path}, which does not ship")
                continue
            label = str(target.relative_to(ROOT))
            if label in seen:
                continue
            seen.add(label)
            body = target.read_text(encoding="utf-8")
            blocks.append({"label": label, "text": body, "kind": "module"})
            queued.append((target, body, "module"))
    return blocks, refused


def compile_with_engine(blocks: list[dict[str, str]], workdir: Path) -> list[str]:
    """Hand each block to a JS engine with the type its document declares, and keep what it refuses."""
    manifest = []
    for index, block in enumerate(blocks):
        path = workdir / f"block{index:03d}{'.mjs' if block['kind'] == 'module' else '.js'}"
        path.write_text(block["text"], encoding="utf-8", newline="\n")
        manifest.append({"label": block["label"], "path": str(path), "kind": block["kind"]})
    assert manifest, "no block was handed to the engine, so this check reads nothing"
    check = workdir / "compile.mjs"
    check.write_text(_ENGINE_COMPILER, encoding="utf-8", newline="\n")
    index_path = workdir / "manifest.json"
    index_path.write_text(json.dumps(manifest), encoding="utf-8")
    run = subprocess.run(
        ["node", "--experimental-vm-modules", str(check), str(index_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=180,
    )
    assert run.returncode == 0, run.stderr
    return [line for line in run.stdout.splitlines() if "::" in line]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_script_the_shipped_sheets_hand_the_browser_compiles(tmp_path: Path) -> None:
    """A sheet is text the product ships, and the only reader that matters is the one that runs it.

    Measured the week this guard was written: a comment inside the extension's webview carried backticks,
    which ended the template literal the host evaluates, and a `split('\\n')` in that same literal became a
    raw newline inside a string. The document reached the webview as a page whose script cannot compile, so
    the panel opened no socket at all, while every source-level assertion stayed green on the text.
    """
    blocks, refused = document_scripts(shipped_sheets())
    assert refused == [], f"the browser is asked for things it cannot get: {refused}"
    assert compile_with_engine(blocks, tmp_path) == []


def test_the_sheet_reader_notices_a_reference_the_browser_cannot_get() -> None:
    popup_index = ROOT / "extension" / "src" / "popup" / "index.html"
    intact, refused = document_scripts({popup_index: '<script type="module" src="popup.js"></script>'})
    assert refused == [] and intact, "the popup's own module was refused"

    _blocks, refused = document_scripts({popup_index: '<script src="popup-not-there.js"></script>'})
    assert refused and "does not ship" in refused[0], "a popup that loads nothing was accepted"

    _blocks, refused = document_scripts(
        {popup_index: '<script type="module">import { no } from "./missing.js";</script>'}
    )
    assert refused and "imports" in refused[0], "a module graph with a hole in it was accepted"

    _blocks, refused = document_scripts(
        {ROOT / "site" / "index.html": '<script type="application/ld+json">{"a": 1,}</script>'}
    )
    assert refused and "not JSON" in refused[0], "the crawler payload was never parsed"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_engine_honours_the_type_the_document_declares(tmp_path: Path) -> None:
    """The popup's modules are only valid as modules. If the reader guessed the kind instead of reading the
    tag, this whole surface would be measured as code no browser accepts, and the guess would go unseen."""
    popup_index = ROOT / "extension" / "src" / "popup" / "index.html"
    blocks, refused = document_scripts({popup_index: '<script src="popup.js"></script>'})
    assert refused == [] and blocks[0]["kind"] == "classic", "a src without a type was not read as classic"

    module_blocks, _refused = document_scripts({popup_index: '<script type="module" src="popup.js"></script>'})
    source = next(block["text"] for block in module_blocks if block["label"].endswith("popup.js"))
    assert compile_with_engine([{"label": "popup.js as classic", "text": source, "kind": "classic"}], tmp_path), (
        "a module read as a classic script compiled anyway, so the declared type was never the thing measured"
    )

from __future__ import annotations

from pathlib import Path

from raven.core.design_tokens import DesignTokens


def _sample_data():
    return {
        "version": "1.0.0",
        "colors": {
            "bg": {"primary": "#0f1117", "secondary": "#1a1d2e"},
            "accent": {"default": "#7c3aed", "hover": "#8b5cf6"},
            "text": {"primary": "#e4e4e7"},
        },
        "spacing": {"md": "1rem", "lg": "1.5rem"},
        "typography": {
            "font-family": {"sans": "Inter, sans-serif", "mono": "monospace"},
            "font-size": {"base": "1rem", "lg": "1.125rem"},
        },
        "border-radius": {"md": "0.5rem", "lg": "0.75rem"},
        "shadow": {"md": "0 4px 6px rgba(0,0,0,0.3)"},
    }


def test_design_tokens_load():
    dt = DesignTokens(_sample_data())
    assert dt.version == "1.0.0"


def test_design_tokens_color():
    dt = DesignTokens(_sample_data())
    assert dt.color("bg", "primary") == "#0f1117"
    assert dt.color("accent", "default") == "#7c3aed"


def test_design_tokens_spacing():
    dt = DesignTokens(_sample_data())
    assert dt.spacing("md") == "1rem"
    assert dt.spacing("lg") == "1.5rem"
    assert dt.spacing("nonexistent") == "1rem"


def test_design_tokens_font_size():
    dt = DesignTokens(_sample_data())
    assert dt.font_size("base") == "1rem"
    assert dt.font_size("lg") == "1.125rem"


def test_design_tokens_font_family():
    dt = DesignTokens(_sample_data())
    assert "Inter" in dt.font_family("sans")
    assert dt.font_family("mono") == "monospace"


def test_design_tokens_border_radius():
    dt = DesignTokens(_sample_data())
    assert dt.border_radius("md") == "0.5rem"
    assert dt.border_radius("lg") == "0.75rem"
    assert dt.border_radius("nonexistent") == "0"


def test_design_tokens_shadow():
    dt = DesignTokens(_sample_data())
    assert "rgba" in dt.shadow("md")
    assert dt.shadow("nonexistent") == "none"


def test_design_tokens_get():
    dt = DesignTokens(_sample_data())
    assert dt.get("version") == "1.0.0"
    assert dt.get("colors", "bg", "primary") == "#0f1117"
    assert dt.get("nonexistent", default="fallback") == "fallback"


def test_design_tokens_to_dict():
    dt = DesignTokens(_sample_data())
    d = dt.to_dict()
    assert d["version"] == "1.0.0"
    assert "colors" in d


def test_design_tokens_colors_property():
    dt = DesignTokens(_sample_data())
    assert "bg" in dt.colors
    assert "accent" in dt.colors


def test_design_tokens_spacing_property():
    dt = DesignTokens(_sample_data())
    assert "md" in dt.spacing_map
    assert dt.spacing_map["md"] == "1rem"


def test_design_tokens_to_css_vars():
    dt = DesignTokens(_sample_data())
    css = dt.to_css_vars()
    assert ":root {" in css
    assert "--dt-version" in css
    assert "--dt-colors-bg-primary" in css
    assert "--dt-spacing-md" in css
    assert css.strip().endswith("}")


def test_design_tokens_to_css_vars_custom_prefix():
    dt = DesignTokens(_sample_data())
    css = dt.to_css_vars(prefix="--rv")
    assert "--rv-version" in css
    assert "--rv-colors-bg-primary" in css


def test_design_tokens_load_empty():
    dt = DesignTokens({})
    assert dt.version == ""
    assert dt.colors == {}
    assert dt.spacing_map == {}


def test_design_tokens_load_from_file(tmp_path: Path):
    p = tmp_path / "tokens.json"
    p.write_text('{"version": "test", "colors": {"accent": {"default": "#ff0000"}}}', encoding="utf-8")
    dt = DesignTokens.load(p)
    assert dt.version == "test"
    assert dt.color("accent", "default") == "#ff0000"


def test_design_tokens_load_missing_file():
    dt = DesignTokens.load("/nonexistent/path/tokens.json")
    assert dt.to_dict() == {}

from __future__ import annotations

import pytest

from raven.core.commands_api import (
    _DEFAULT_ACCENT,
    _coerce_palette,
    _complete_palette,
    _deterministic_palette,
    _hex_to_rgba,
    _hsl_to_hex,
    _is_valid_hex,
)


def test_is_valid_hex() -> None:
    assert _is_valid_hex("#aabbcc") is True
    assert _is_valid_hex("#AABBCC") is True
    assert _is_valid_hex("#123456") is True
    assert _is_valid_hex("#gg0000") is False
    assert _is_valid_hex("aabbcc") is False
    assert _is_valid_hex("#abc") is False
    assert _is_valid_hex("") is False


def test_hsl_to_hex() -> None:
    result = _hsl_to_hex(0, 1.0, 0.5)
    assert _is_valid_hex(result)
    assert result == "#ff0000"

    result = _hsl_to_hex(120, 1.0, 0.5)
    assert result == "#00ff00"

    result = _hsl_to_hex(240, 1.0, 0.5)
    assert result == "#0000ff"


def test_hsl_to_hex_wraps() -> None:
    result = _hsl_to_hex(360, 1.0, 0.5)
    assert _is_valid_hex(result)


def test_hex_to_rgba() -> None:
    assert _hex_to_rgba("#ff0000", 1.0) == "rgba(255, 0, 0, 1.0)"
    assert _hex_to_rgba("#00ff00", 0.5) == "rgba(0, 255, 0, 0.5)"
    assert _hex_to_rgba("#0000ff", 0.0) == "rgba(0, 0, 255, 0.0)"


def test_deterministic_palette() -> None:
    palette = _deterministic_palette("test-seed")
    assert "bg" in palette
    assert "surface" in palette
    assert "accent" in palette
    assert "text" in palette
    assert "border" in palette
    assert "status" in palette

    assert "primary" in palette["bg"]
    assert "default" in palette["accent"]
    assert _is_valid_hex(palette["accent"]["default"])


def test_deterministic_palette_same_seed() -> None:
    p1 = _deterministic_palette("same-seed")
    p2 = _deterministic_palette("same-seed")
    assert p1 == p2


def test_deterministic_palette_different_seed() -> None:
    p1 = _deterministic_palette("seed-a")
    p2 = _deterministic_palette("seed-b")
    assert p1["accent"]["default"] != p2["accent"]["default"]


def test_coerce_palette_valid() -> None:
    raw = {
        "bg": {"primary": "#0a0b0c", "secondary": "#1a1b1c"},
        "accent": {"default": "#7c3aed"},
    }
    result = _coerce_palette(raw)
    assert "bg" in result
    assert "accent" in result
    assert result["bg"]["primary"] == "#0a0b0c"


def test_coerce_palette_invalid_hex() -> None:
    raw = {
        "bg": {"primary": "not-a-color", "secondary": "#abc"},
        "accent": {"default": "#7c3aed"},
    }
    result = _coerce_palette(raw)
    assert "bg" not in result or result["bg"] == {}
    assert "accent" in result


def test_coerce_palette_not_dict() -> None:
    assert _coerce_palette("not a dict") == {}
    assert _coerce_palette(None) == {}


def test_complete_palette() -> None:
    base = _deterministic_palette("test")
    overrides = {"accent": {"default": "#ff0000"}}
    merged = _complete_palette(base, overrides)
    assert merged["accent"]["default"] == "#ff0000"
    assert merged["bg"] == base["bg"]


def test_complete_palette_invalid_override() -> None:
    base = _deterministic_palette("test")
    overrides = {"accent": {"default": "invalid"}}
    merged = _complete_palette(base, overrides)
    assert merged["accent"]["default"] == base["accent"]["default"]


def test_default_accent_is_valid() -> None:
    assert _is_valid_hex(_DEFAULT_ACCENT)

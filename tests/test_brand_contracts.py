from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_product_name_is_raven() -> None:
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    webchat = (ROOT / "raven" / "channels" / "webchat" / "channel.py").read_text(encoding="utf-8")

    assert "site_name: Raven" in mkdocs
    assert manifest["name"] == "Raven"
    assert manifest["action"]["default_title"] == "Raven"
    assert "<title>Raven</title>" in webchat
    assert (ROOT / "docs" / "stylesheets" / "fonts" / "IBMPlexSans-latin.woff2").is_file()
    assert (ROOT / "extension" / "assets" / "fonts" / "IBMPlexSans-latin.woff2").is_file()


def test_public_surfaces_do_not_use_the_old_ai_suffix() -> None:
    for relative in [
        "docs/index.md",
        "docs/cli.md",
        "docs/concepts/architecture.md",
        "docs/plugins.md",
        "docs/channels/overview.md",
        "extension/manifest.json",
        "extension/src/background.js",
        "web/index.html",
    ]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "Raven AI" not in text, relative

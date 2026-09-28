"""Single-product-version invariant.

Every place that declares the Raven version (packaging, CLIs, MCP handshakes, TUI,
API servers, web SPA, extensions) must agree with ``pyproject.toml``. Regression
guard for the "version bump across all modules" promise in CHANGELOG.
"""

from __future__ import annotations

import json
import re
import struct
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parent.parent

_VERSION = r"([0-9]+\.[0-9]+\.[0-9]+)"

# (relative path, regex with exactly one capture group holding the declared version)
VERSION_SURFACES: tuple[tuple[str, str], ...] = (
    ("Dockerfile", rf"ARG RAVEN_VERSION={_VERSION}"),
    ("deploy/docker-compose.yml", rf"RAVEN_VERSION:-{_VERSION}"),
    ("deploy/docker-compose.override.prod.yml", rf"RAVEN_VERSION:-{_VERSION}"),
    ("raven/cli/init_cmd.py", rf'CONFIG_STORE_VERSION = "{_VERSION}"'),
    ("raven/cli/init_cmd.py", rf'"version": "{_VERSION}"'),
    ("raven/cli/setup_cmd.py", rf'"version": "{_VERSION}"'),
    ("raven/core/mcp/mcp_client.py", rf'"name": "raven-mcp-client", "version": "{_VERSION}"'),
    ("raven/core/mcp/server.py", rf'"name": "raven-mcp", "version": "{_VERSION}"'),
    ("raven/tui/app.py", rf'SUB_TITLE = "v{_VERSION}'),
    ("raven/gateway/daemon.py", rf'title="RavenFlow Gateway",\s*version="{_VERSION}"'),
    ("ravencode/api/server.py", rf'title="RavenCode API",\s*version="{_VERSION}"'),
    ("ravencode/mcp/server.py", rf'"name": "ravencode", "version": "{_VERSION}"'),
    ("web/package.json", rf'"version": "{_VERSION}"'),
    ("web/package-lock.json", rf'"name": "raven-web",\s*"version": "{_VERSION}"'),
    ("extension/manifest.json", rf'"version": "{_VERSION}"'),
    ("extension/vscode/package.json", rf'"version": "{_VERSION}"'),
    ("extension/vscode/package-lock.json", rf'"name": "raven-vscode",\s*"version": "{_VERSION}"'),
    (".env.example", rf"SERVICE_VERSION={_VERSION}"),
)


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _png_size(path: Path) -> tuple[int, int]:
    """Read width/height straight from the PNG IHDR chunk (no image dependency)."""
    header = path.read_bytes()[:24]
    return struct.unpack(">II", header[16:24])


def _load_json(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("rel_path", "pattern"),
    VERSION_SURFACES,
    ids=[f"{i}-{path}" for i, (path, _) in enumerate(VERSION_SURFACES)],
)
def test_declared_version_matches_pyproject(rel_path: str, pattern: str) -> None:
    expected = _project_version()
    text = (ROOT / rel_path).read_text(encoding="utf-8")
    found = re.findall(pattern, text)
    assert found, f"{rel_path} no longer declares a version matching {pattern!r}"
    mismatched = [value for value in found if value != expected]
    assert mismatched == [], f"{rel_path} declares {mismatched}, expected {expected}"


def test_chrome_manifest_assets_exist() -> None:
    ext_dir = ROOT / "extension"
    manifest = _load_json(ext_dir / "manifest.json")
    icons = manifest["icons"]
    assert isinstance(icons, dict)
    referenced = [
        *icons.values(),
        manifest["action"]["default_popup"],
        manifest["side_panel"]["default_path"],
        manifest["background"]["service_worker"],
    ]
    missing = [rel for rel in referenced if not (ext_dir / str(rel)).is_file()]
    assert missing == [], f"Chrome manifest references missing files: {missing}"
    for declared_size, rel in icons.items():
        assert _png_size(ext_dir / str(rel)) == (int(declared_size), int(declared_size))


def test_vscode_icon_matches_manifest() -> None:
    vscode_dir = ROOT / "extension" / "vscode"
    package = _load_json(vscode_dir / "package.json")
    icon = vscode_dir / str(package["icon"])
    assert icon.is_file(), f"vsce packaging needs {icon.relative_to(ROOT)}"
    width, height = _png_size(icon)
    assert width == height
    assert width >= 128, "VS Code marketplace requires an icon of at least 128x128"


def test_package_versions_match_pyproject() -> None:
    import raven
    import ravencode

    expected = _project_version()
    assert raven.__version__ == expected
    assert ravencode.__version__ == expected


def test_cli_version_flags() -> None:
    from click.testing import CliRunner

    from raven.cli.main import cli as raven_cli
    from ravencode.cli.main import cli as ravencode_cli

    expected = _project_version()
    for cli, prog in ((raven_cli, "raven"), (ravencode_cli, "ravencode")):
        result = CliRunner().invoke(cli, ["--version"])
        assert result.exit_code == 0, result.output
        assert prog in result.output
        assert expected in result.output


def test_web_sidebar_badge_uses_package_json_version() -> None:
    layout = (ROOT / "web" / "src" / "components" / "Layout.tsx").read_text(encoding="utf-8")
    assert 'from "../../package.json"' in layout, "sidebar version badge must read web/package.json"
    assert "VITE_APP_VERSION" not in layout, "no hardcoded version fallback in the sidebar badge"

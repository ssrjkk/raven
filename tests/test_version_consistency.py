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
    ("raven/core/mcp/server.py", rf'server_version: str = "{_VERSION}"'),
    ("raven/tui/app.py", rf'SUB_TITLE = "v{_VERSION}'),
    ("raven/gateway/daemon.py", rf'title="RavenFlow Gateway",\s*version="{_VERSION}"'),
    ("ravencode/api/server.py", rf'title="RavenCode API",\s*version="{_VERSION}"'),
    ("web/package.json", rf'"version": "{_VERSION}"'),
    ("web/package-lock.json", rf'"name": "raven-web",\s*"version": "{_VERSION}"'),
    ("extension/manifest.json", rf'"version": "{_VERSION}"'),
    ("extension/vscode/package.json", rf'"version": "{_VERSION}"'),
    ("extension/vscode/package-lock.json", rf'"name": "raven-vscode",\s*"version": "{_VERSION}"'),
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


def _project_table() -> dict[str, object]:
    return cast("dict[str, object]", tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"])


def _python_floor_minor() -> int:
    """The minor the package actually requires, straight out of ``requires-python``."""
    match = re.search(r">=\s*3\.(\d+)", str(_project_table()["requires-python"]))
    assert match is not None, "requires-python no longer states a >=3.x floor"
    return int(match.group(1))


PROSE_SURFACES = ("README.md", "README.ru.md")


def test_every_python_floor_claim_matches_the_package_requirement() -> None:
    """A front page that says 3.12+ while `requires-python` says >=3.11 turns a supported install
    into a supposed incompatibility, and the claim was sitting in a badge nobody was checking."""
    floor = _python_floor_minor()
    for rel in PROSE_SURFACES:
        claims = set(re.findall(r"Python 3\.(\d+)\+", (ROOT / rel).read_text(encoding="utf-8")))
        assert claims and claims == {str(floor)}, f"{rel} claims {claims}, package requires 3.{floor}+"
    for path in sorted((ROOT / "site").glob("*.html")):
        claims = set(re.findall(r"Python 3\.(\d+)\+", path.read_text(encoding="utf-8")))
        assert claims <= {str(floor)}, f"{path.name} claims {claims}"
    for path in sorted((ROOT / "docs").rglob("*.md")):
        if "archive" in path.parts:
            continue
        claims = set(re.findall(r"Python 3\.(\d+)\+", path.read_text(encoding="utf-8")))
        assert claims <= {str(floor)}, f"{path.relative_to(ROOT)} claims {claims}"


def test_the_readme_states_the_python_versions_ci_actually_runs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    matrix = re.findall(
        r"python-version: \[\"([\d.]+)\"(?:, \"([\d.]+)\")?\]",
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
    )
    tested = sorted({value for pair in matrix for value in pair if value})
    assert tested, "the CI matrix no longer names python-version values"
    claimed = re.search(r"Python ([\d.]+) and ([\d.]+)", readme)
    assert claimed is not None, "README no longer names the interpreters CI runs"
    assert sorted([claimed.group(1), claimed.group(2)]) == tested


def test_the_front_page_asks_nothing_of_a_third_party_host() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[![" not in readme, "a status badge is a request to a host the project does not run"
    assert "img.shields.io" not in readme
    assert "<img" not in readme


def test_every_installed_command_is_documented() -> None:
    """`pip install` puts these names on the PATH: a command neither README mentions is a feature
    the operator never finds, and a named command packaging does not install is a lie. Both
    READMEs are checked because their tables are translations of one another and drift apart."""
    scripts = set(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"])
    for rel in PROSE_SURFACES:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith("| `raven start`")]
        assert starts, f"{rel} has no command table"
        rows = []
        for line in lines[starts[0] :]:
            if not line.startswith("| `"):
                break
            rows.append(line)
        named = {re.match(r"^\| `([a-z0-9-]+)", row).group(1) for row in rows}  # type: ignore[union-attr]
        assert named == scripts, f"{rel} lists {sorted(named)}, packaging installs {sorted(scripts)}"

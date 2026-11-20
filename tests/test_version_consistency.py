"""Single-product-version invariant.

Every place that declares the Raven version (packaging, CLIs, MCP handshakes, TUI,
API servers, web SPA, extensions) must agree with ``pyproject.toml``. Regression
guard for the "version bump across all modules" promise in CHANGELOG.
"""

from __future__ import annotations

import asyncio
import json
import re
import struct
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


# A declaring file can carry the right version and still answer with a different one: `/api/status` and
# `/api/admin/system/status` reported the string `"1.0.0"`, and `/aios/health` reported `"0.1.0"`, while every
# file the list above pins said `0.4.8`. These are the answers the console puts on screen, so they are asked,
# not read out of a source file.
VERSION_ANSWERS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("/api/status", lambda: _status_client().get("/api/status").json()["version"]),
    ("/api/admin/system/status", lambda: _admin_client().get("/api/admin/system/status").json()["version"]),
    ("/aios/health", lambda: asyncio.run(_aios_health())["version"]),
)


def _status_client() -> TestClient:
    from raven.core.status_api import create_status_router

    gateway = MagicMock()
    gateway.channels.list_ids = AsyncMock(return_value=[])
    gateway.registry.list_agents.return_value = []
    loader = MagicMock()
    loader.tools = []
    app = FastAPI()
    app.include_router(create_status_router(gateway, loader, asyncio.Event()))
    return TestClient(app)


def _admin_client() -> TestClient:
    from raven.core.admin_api import create_admin_router

    channels = SimpleNamespace(list_ids=AsyncMock(return_value=[]))
    registry = SimpleNamespace(list_agents=lambda: [])
    gateway = SimpleNamespace(is_running=False)
    app = FastAPI()
    app.include_router(create_admin_router(lambda: channels, lambda: registry, lambda: gateway))
    return TestClient(app)


async def _aios_health() -> dict[str, Any]:
    from aios.api.bridge import aios_health

    return cast("dict[str, Any]", await aios_health())


@pytest.mark.parametrize(("route", "answer"), VERSION_ANSWERS, ids=[route for route, _ in VERSION_ANSWERS])
def test_the_version_an_http_surface_answers_is_the_running_products_own(route: str, answer: Callable[[], str]) -> None:
    expected = _project_version()
    found = answer()
    assert found == expected, f"{route} answers version {found!r}, the running package is {expected!r}"


#: Sites whose answer must be `raven.core.version` rather than a version typed into the return statement. A
#: literal here is correct until the next release and silently wrong after it, which is what these two routes
#: were: the pin fails the moment the literal is written back, not when the version moves.
VERSION_DERIVED_SITES: tuple[tuple[str, str], ...] = (
    ("raven/core/status_api.py", r'"version": __version__'),
    ("raven/core/admin_api.py", r'"version": __version__'),
    ("aios/api/bridge.py", r'"version": __version__'),
    ("raven/channels/webchat/channel.py", r'"__VERSION__", __version__'),
)


@pytest.mark.parametrize(
    ("rel_path", "pattern"), VERSION_DERIVED_SITES, ids=[path for path, _ in VERSION_DERIVED_SITES]
)
def test_the_version_answer_is_read_from_the_version_module(rel_path: str, pattern: str) -> None:
    text = (ROOT / rel_path).read_text(encoding="utf-8")
    assert re.search(pattern, text), f"{rel_path} no longer answers with raven.core.version.__version__"
    assert not re.search(r'version"?\s*[:=]\s*"[0-9]+\.[0-9]+\.[0-9]+"', text), (
        f"{rel_path} both derives the version and carries a version literal"
    )


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


#: An unpacked extension has no bundler between the source and the browser: a document that asks for a
#: file the package does not hold gets a silent 404 at load time, and the surface arrives without its
#: stylesheet, its mark or its type.
POPUP_DIR = ROOT / "extension" / "src" / "popup"
#: A `url()` value, quoted or bare. The quoted alternatives have to be matched first and whole: the grain
#: filter these surfaces inline as `url("data:image/svg+xml,…")` carries its own `filter='url(%23n)'`
#: inside the quotes, and a value class that stops at the first `)` reads that fragment as a file the
#: package must ship — which is how the popup was accused of asking for `%23n`.
_ASSET_REQUEST = re.compile(
    r"""(?:src|href)="(?P<attr>[^"]+)"|url\(\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^'")\s]+))\s*\)"""
)
_NOT_A_PACKAGED_FILE = re.compile(r"(?:[a-z]+:)?(?://|#|data:)", re.IGNORECASE)


def asset_requests(document_text: str) -> list[str]:
    """The packaged files one popup document asks for, ignoring remote, runtime and inlined URLs."""
    found: list[str] = []
    for match in _ASSET_REQUEST.finditer(document_text):
        ref = next((group for group in match.groups() if group), "")
        if ref and not _NOT_A_PACKAGED_FILE.match(ref):
            found.append(ref)
    return found


def popup_documents() -> list[Path]:
    return sorted(path for path in POPUP_DIR.iterdir() if path.suffix in {".html", ".css", ".js"})


def test_the_popup_ships_every_file_its_documents_ask_for() -> None:
    documents = popup_documents()
    assert documents, f"{POPUP_DIR.relative_to(ROOT)} holds no documents, so this guard reads nothing"
    missing = [
        f"{document.name} asks for {ref}"
        for document in documents
        for ref in asset_requests(document.read_text(encoding="utf-8"))
        if not (POPUP_DIR / ref).is_file()
    ]
    assert not missing, "the popup would load these and get nothing:\n" + "\n".join(missing)
    asked = {ref for document in documents for ref in asset_requests(document.read_text(encoding="utf-8"))}
    assert "raven.svg" in asked, "the popup header no longer asks for the brand mark the site ships"


def test_the_asset_reader_notices_a_request_that_points_nowhere() -> None:
    markup = (POPUP_DIR / "index.html").read_text(encoding="utf-8")
    renamed = markup.replace('src="raven.svg"', 'src="bird.svg"')  # the mistake: an asset renamed or edited out
    assert renamed != markup, "the popup no longer asks for raven.svg, so this proof tests nothing"
    assert "bird.svg" in asset_requests(renamed), "a renamed asset escaped the reader"
    assert not (POPUP_DIR / "bird.svg").is_file(), "bird.svg exists, so the planted reference is no violation"


def test_the_asset_reader_reads_a_fragment_inside_an_inlined_url_as_bytes_not_as_a_file() -> None:
    """The grain filter ships inside the stylesheet, and it nests a `url(%23n)` of its own.

    Measured: the popup was failed for asking after `%23n`, a fragment identifier inside a `data:` URI the
    browser never resolves as a request. Refusing to descend into a quoted value is what this proves, and the
    bare form still has to be read — otherwise the reader would pass a stylesheet whose fonts were renamed."""
    css = (POPUP_DIR / "popup.css").read_text(encoding="utf-8")
    assert 'url("data:' in css and "url(%23n)" in css, (
        "the popup no longer inlines a URI with a nested url(), so this reads nothing"
    )
    assert not [ref for ref in asset_requests(css) if "%23" in ref], (
        "a fragment inside an inlined URI was read as a packaged file"
    )
    assert "fonts/IBMPlexSans-latin.woff2" in asset_requests(css), (
        "a real font ask stopped being read, so the case above proves nothing"
    )

    dropped = css.replace("url('fonts/IBMPlexSans-latin.woff2')", "url('fonts/IBMPlexSans-gone.woff2')")
    assert dropped != css, "the font ask no longer has the shape this proof renames"
    assert "fonts/IBMPlexSans-gone.woff2" in asset_requests(dropped), "a renamed font file escaped the reader"
    assert not (POPUP_DIR / "fonts/IBMPlexSans-gone.woff2").is_file(), (
        "the planted file exists, so the reference is no violation"
    )


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

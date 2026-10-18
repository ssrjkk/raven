"""Runtime artifacts must land under the configured data dir, never the working directory.

A cwd-relative default once wrote the Ed25519 audit signing key into ``site/data/``,
which the Pages job publishes whole-tree — the key would have gone public.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from raven.core.audit import AUDIT_KEY_FILE, AuditLogger
from raven.core.config import data_path, settings
from raven.core.secrets import SecretsManager
from raven.core.tools_rbac import ToolPolicyStore
from ravencode.runtime.anchored import _ANCHORED_PATH
from ravencode.runtime.checkpoints import CheckpointManager
from ravencode.runtime.context import MemoryStore
from ravencode.runtime.session import SessionStore
from ravencode.runtime.todo import _TODO_PATH

ROOT = Path(__file__).resolve().parents[2]
PROD_PACKAGES = ("raven", "ravencode", "aios")
CWD_RELATIVE_DATA = re.compile(r"""Path\(\s*["']data[/\\]""")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "data" / "raven.db"))
    return tmp_path / "data"


def test_data_path_never_resolves_against_the_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert data_path("sessions") == settings.resolved_data_dir / "sessions"
    assert not data_path("sessions").is_relative_to(tmp_path.resolve())


def test_settings_paths_are_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert settings.resolved_db_path.is_absolute()
    assert settings.resolved_data_dir.is_absolute()
    assert settings.resolved_log_file.is_absolute()


def test_secret_and_session_defaults_follow_the_data_dir(data_dir: Path) -> None:
    assert SecretsManager()._data_dir == data_dir
    assert SessionStore()._storage == data_dir.resolve() / "sessions"
    assert CheckpointManager()._storage == data_dir.resolve() / "checkpoints"
    assert MemoryStore()._target == data_dir / "ravencode_memory.json"
    assert ToolPolicyStore()._path == data_dir / "tool_policy.json"
    assert AuditLogger()._path == data_dir / "audit.log"


def test_module_level_defaults_are_absolute() -> None:
    for path in (Path(AUDIT_KEY_FILE), _ANCHORED_PATH, _TODO_PATH):
        assert path.is_absolute(), path


@pytest.mark.parametrize("pkg", PROD_PACKAGES)
def test_no_cwd_relative_data_paths_in_production(pkg: str) -> None:
    offenders = [
        f"{py.relative_to(ROOT)}:{lineno}"
        for py in sorted((ROOT / pkg).rglob("*.py"))
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1)
        if CWD_RELATIVE_DATA.search(line)
    ]
    assert offenders == []

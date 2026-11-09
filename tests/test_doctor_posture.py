"""`raven doctor` must report what the security settings decide, not echo their names.

Each row is asserted on its marker: [OK] means the control is engaged, [!] means the configuration
says one thing and the code will do another, [ERR] means the value cannot be loaded at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from raven.cli import doctor_cmd
from raven.core.config import Settings

MODE_ROW = "Tool Exec Policy"
WORKSPACE_ROW = "Workspace Confinement"


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """A Settings instance of our own: doctor reads the process-wide one, and the ambient .env here
    would otherwise decide what these tests see."""
    fresh = Settings.model_validate({})
    monkeypatch.setattr(doctor_cmd, "get_settings", lambda: fresh)
    yield fresh


def _posture(**values: Any) -> dict[str, str]:
    state = doctor_cmd.get_settings()
    for key, value in values.items():
        setattr(state, key, value)
    return {label: result for label, result in doctor_cmd.security_posture_checks()}


def test_the_default_policy_reports_what_it_blocks() -> None:
    row = _posture()[MODE_ROW]
    assert row.startswith("[OK]")
    assert "db_query" in row and "plugin_" in row, "the row has to name the class it refuses"


def test_full_exec_mode_is_never_reported_as_ok() -> None:
    row = _posture(exec_security="full")[MODE_ROW]
    assert row.startswith("[!]")
    assert "no confirmation" in row


def test_ask_with_the_confirmation_mode_off_is_a_warning() -> None:
    # EXEC_SECURITY=ask with EXEC_ASK_MODE=off is "run it anyway" wearing an asking name
    row = _posture(exec_security="ask", exec_ask_mode="off")[MODE_ROW]
    assert row.startswith("[!]")
    assert "without asking anyone" in row


def test_ask_with_a_confirmation_mode_is_engaged() -> None:
    row = _posture(exec_security="ask", exec_ask_mode="always")[MODE_ROW]
    assert row.startswith("[OK]")
    assert "refused where nobody can be asked" in row


def test_an_impossible_exec_mode_says_what_breaks() -> None:
    row = _posture(exec_security="permissive")[MODE_ROW]
    assert row.startswith("[ERR]")
    assert "every agent build raises" in row


def test_the_unconfigured_workspace_still_confines_something(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset WORKSPACE_PATH no longer means an unset root: the guard is always armed, and doctor
    says which directory it is armed with and which setting decided it."""
    from raven.core import config as config_module

    monkeypatch.delenv("RAVEN_WORKSPACE", raising=False)
    monkeypatch.delenv("WORKSPACE_PATH", raising=False)
    monkeypatch.setattr(config_module.settings, "workspace_path", "")
    row = _posture(workspace_only=True)[WORKSPACE_ROW]
    assert row.startswith("[OK]")
    assert str(Path.cwd().resolve()) in row
    assert "working directory" in row


def test_workspace_confinement_names_the_root_and_who_decided_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAVEN_WORKSPACE", str(tmp_path))
    row = _posture(workspace_only=True)[WORKSPACE_ROW]
    assert row.startswith("[OK]")
    assert str(tmp_path.resolve()) in row
    assert "RAVEN_WORKSPACE" in row


def test_disabling_confinement_is_a_warning() -> None:
    assert _posture(workspace_only=False)[WORKSPACE_ROW].startswith("[!]")


def test_telemetry_is_reported_as_off_by_default() -> None:
    assert "(telemetry off)" in _posture()["Features"]

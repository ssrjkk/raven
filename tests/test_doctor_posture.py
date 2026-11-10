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


MODEL_ROW = "Bundled Free Model"
NOTE_ROW = "Model Note"


def _model_status(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> dict[str, str]:
    from types import SimpleNamespace

    from raven.core import heretic_model

    defaults: dict[str, Any] = {
        "ref": heretic_model.HERETIC_HF_REF,
        "raven_model": heretic_model.HERETIC_RAVEN_MODEL,
        "size_gb": heretic_model.HERETIC_SIZE_GB,
        "ollama_reachable": True,
        "present": False,
        "is_default": False,
        "default_model": "groq/openai/gpt-oss-120b",
        "hardware": SimpleNamespace(summary=lambda: "24.0 of 32.0 GB RAM free, 500.0 GB disk free, 24576 MB VRAM"),
        "blockers": [],
        "warnings": [],
    }
    defaults.update(fields)
    monkeypatch.setattr(heretic_model, "status", lambda *_a, **_k: SimpleNamespace(**defaults))
    return {label: result for label, result in doctor_cmd.experimental_model_checks()}


def test_the_row_uses_the_hardware_it_measured_when_the_model_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _model_status(monkeypatch, is_default=True)[MODEL_ROW]
    assert row.startswith("[OK]")
    assert "24.0 of 32.0 GB RAM free" in row


def test_a_refusing_preflight_is_said_with_its_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _model_status(monkeypatch, blockers=["0.9 GB RAM free with 0 MB of VRAM to offload to"])[MODEL_ROW]
    assert row.startswith("[!]") and "0.9 GB RAM free" in row


def test_weights_already_in_ollama_only_need_the_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _model_status(monkeypatch, present=True)[MODEL_ROW]
    assert "pulled, not in use" in row and "raven models enable-heretic" in row


def test_the_download_is_costed_before_it_is_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core.heretic_model import HERETIC_SIZE_GB

    row = _model_status(monkeypatch)[MODEL_ROW]
    assert f"{HERETIC_SIZE_GB:.2f} GB" in row and "raven models enable-heretic" in row


def test_a_tier_that_still_bills_appears_as_a_note(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _model_status(monkeypatch, warnings=["MODEL_FAST=groq/openai/gpt-oss-120b still bills a hosted provider"])
    assert rows[NOTE_ROW].startswith("[!]") and "MODEL_FAST" in rows[NOTE_ROW]


def test_a_probe_that_throws_does_not_blank_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core import heretic_model

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no disk here")

    monkeypatch.setattr(heretic_model, "status", _boom)
    row = doctor_cmd.experimental_model_checks()[0]
    assert row[0] == MODEL_ROW and row[1].startswith("[ERR]") and "no disk here" in row[1]

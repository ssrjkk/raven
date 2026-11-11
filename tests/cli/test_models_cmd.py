"""`raven models` and the two heretic switches, at the exact boundary the operator stands at.

The download prompt is the only thing between a typo and 5.63 GB, so it is tested with a real
non-tty stdin: a prompt that silently proceeds in CI or in a script is the failure this guards.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from raven.cli import models_cmd
from raven.core.heretic_model import HERETIC_HF_REF, HERETIC_SIZE_GB, SwitchResult


@pytest.fixture(autouse=True)
def _no_calls_out_of_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing below may reach Ollama, Hugging Face or the real env files."""
    monkeypatch.setattr(models_cmd, "enable", lambda *_a, **_k: pytest.fail("enable ran unstubbed"))
    monkeypatch.setattr(models_cmd, "disable", lambda *_a, **_k: pytest.fail("disable ran unstubbed"))
    monkeypatch.setattr(
        models_cmd,
        "status",
        lambda *_a, **_k: pytest.fail("status ran unstubbed"),
    )


class _FakeHardware:
    ram_total_gb = 32.0
    ram_free_gb = 24.0
    disk_free_gb = 500.0
    vram_mb = 24576

    def summary(self) -> str:
        return "24.0 of 32.0 GB RAM free, 500.0 GB disk free, 24576 MB VRAM"


def _status(is_default: bool = False, present: bool = True, blockers: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        ref=HERETIC_HF_REF,
        raven_model=f"ollama/{HERETIC_HF_REF}",
        size_gb=HERETIC_SIZE_GB,
        ollama_reachable=True,
        present=present,
        is_default=is_default,
        default_model=f"ollama/{HERETIC_HF_REF}" if is_default else "groq/openai/gpt-oss-120b",
        hardware=_FakeHardware(),
        blockers=blockers or [],
        env_file=Path("C:/fake/.env"),
        warnings=[] if present else [f"not pulled ({HERETIC_SIZE_GB:.2f} GB, run: raven models enable-heretic)"],
    )


def test_models_list_shows_the_bundled_model_and_how_to_turn_it_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status())
    result = CliRunner().invoke(models_cmd.models_group, ["list"])
    assert result.exit_code == 0, result.output
    assert "Bundled free experimental model" in result.output
    assert f"{HERETIC_SIZE_GB:.2f} GB" in result.output
    assert "raven models enable-heretic" in result.output


class TestEnableHeredic:
    def test_refuses_to_download_without_a_tty_and_without_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status(present=False))
        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(models_cmd, "enable", lambda *_a, **_k: calls.append(dict(_k)))

        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic"], input="y\n")

        assert result.exit_code == 1, result.output
        assert "refusing to download" in result.output and f"{HERETIC_SIZE_GB:.2f} GB" in result.output
        assert calls == [], "the switch must not be written when the download was refused"

    def test_yes_runs_the_pull_and_shows_what_was_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status(present=False))
        seen: dict[str, Any] = {}

        def _enable(url: str, **kwargs: Any) -> SwitchResult:
            seen.update(url=url, **kwargs)
            return SwitchResult(ok=True, detail="DEFAULT_MODEL=ollama/x", env_file=Path("C:/fake/.env"), pulled=True)

        monkeypatch.setattr(models_cmd, "enable", _enable)
        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic", "--yes"])
        assert result.exit_code == 0, result.output
        assert seen["pull"] is True and seen["force"] is False
        # Rich re-renders separators for the host platform, so the path is checked by its parts.
        assert "Written to:" in result.output and "fake" in result.output and ".env" in result.output
        assert "within 5 s" in result.output

    def test_no_pull_switches_without_touching_the_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status(present=True))
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            models_cmd,
            "enable",
            lambda url, **kwargs: (
                seen.update(kwargs)
                or SwitchResult(ok=True, detail="DEFAULT_MODEL=ollama/x", env_file=Path("C:/fake/.env"))
            ),
        )
        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic", "--no-pull"])
        assert result.exit_code == 0, result.output
        assert seen == {"pull": False, "force": False}

    def test_blockers_are_printed_before_the_choice_and_a_refusal_is_exit_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            models_cmd, "status", lambda *_a, **_k: _status(present=False, blockers=["0.9 GB RAM free"])
        )
        monkeypatch.setattr(
            models_cmd,
            "enable",
            lambda *_a, **_k: SwitchResult(ok=False, detail="host cannot run this model", blockers=["0.9 GB RAM free"]),
        )
        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic", "--yes"])
        assert result.exit_code == 1
        assert "blocked" in result.output and "0.9 GB RAM free" in result.output
        assert "host cannot run this model" in result.output

    def test_force_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status(present=True, blockers=["0.9 GB RAM free"]))
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            models_cmd,
            "enable",
            lambda url, **kwargs: (
                seen.update(kwargs)
                or SwitchResult(ok=True, detail="DEFAULT_MODEL=ollama/x", env_file=Path("C:/fake/.env"))
            ),
        )
        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic", "--force"])
        assert result.exit_code == 0, result.output
        assert seen == {"pull": True, "force": True}

    def test_warnings_reach_the_operator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(models_cmd, "status", lambda *_a, **_k: _status())
        monkeypatch.setattr(
            models_cmd,
            "enable",
            lambda *_a, **_k: SwitchResult(
                ok=True,
                detail="DEFAULT_MODEL=ollama/x",
                env_file=Path("C:/fake/.env"),
                warnings=["MODEL_QUALITY=anthropic/claude-sonnet-4-5 still bills a hosted provider"],
            ),
        )
        result = CliRunner().invoke(models_cmd.models_group, ["enable-heretic", "--no-pull"])
        assert "still bills a hosted provider" in result.output


def test_disable_reports_a_restore_failure_as_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models_cmd, "disable", lambda: SwitchResult(ok=False, detail="nothing to restore: no key"))
    result = CliRunner().invoke(models_cmd.models_group, ["disable-heretic"])
    assert result.exit_code == 1 and "nothing to restore" in result.output


def test_disable_names_the_model_it_put_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        models_cmd,
        "disable",
        lambda: SwitchResult(ok=True, detail="DEFAULT_MODEL=groq/openai/gpt-oss-120b", env_file=Path("C:/fake/.env")),
    )
    result = CliRunner().invoke(models_cmd.models_group, ["disable-heretic"])
    assert result.exit_code == 0, result.output
    assert "groq/openai/gpt-oss-120b" in result.output

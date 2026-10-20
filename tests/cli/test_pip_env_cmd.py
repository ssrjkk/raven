# ruff: noqa: RUF002 (intentional Cyrillic in Russian comments)
"""CLI не зовёт установщик пакетов там, где его нет (контейнер собирается без него)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from raven.cli.main import cli
from raven.cli.pip_env import MISSING_PIP, pip_available


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestPipAvailable:
    def test_true_when_module_found(self) -> None:
        with patch("raven.cli.pip_env.importlib.util.find_spec", return_value=MagicMock()):
            assert pip_available() is True

    def test_false_when_module_missing(self) -> None:
        with patch("raven.cli.pip_env.importlib.util.find_spec", return_value=None):
            assert pip_available() is False


class TestUpdateWithoutPip:
    def test_update_reports_missing_pip_and_never_subprocesses(self, runner: CliRunner) -> None:
        with patch("raven.cli.main.pip_available", return_value=False):
            with patch("subprocess.run", side_effect=AssertionError("pip was called")) as run:
                result = runner.invoke(cli, ["update", "--dry-run"])
        assert result.exit_code == 0
        assert "pip is not installed" in result.output
        run.assert_not_called()

    def test_update_still_runs_with_pip_present(self, runner: CliRunner) -> None:
        with patch("raven.cli.main.pip_available", return_value=True):
            with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="Requirement already satisfied")):
                result = runner.invoke(cli, ["update", "--dry-run"])
        assert result.exit_code == 0
        assert "pip is not installed" not in result.output

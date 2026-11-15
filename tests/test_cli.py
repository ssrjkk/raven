from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from raven.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def _a_command_adopts_only_this_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pin_env_names: Callable[[Iterable[str]], None],
) -> Path:
    """Aim the env-file cascade at a file this test owns.

    ``raven doctor`` adopts the files, and every command that builds a gateway adopts them through
    ``create_gateway`` — that is the whole of wave #143, and it is what a standalone process needs. In a
    shared test process it would export the operator's own ``GROQ_API_KEY``, ``LOG_LEVEL`` and
    ``TELEGRAM_BOT_TOKEN`` into every later test, so the cascade is redirected here and the switch names are
    handed to ``pin_env_names``, which takes them out of the run and puts back what the run had.
    """
    from raven.core import config as config_module
    from raven.core.config import runtime_switches

    env = tmp_path / ".env-cli-run"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_module, "_ENV_FILE_CANDIDATES", [str(env)])
    pin_env_names(switch.env_name for switch in runtime_switches())
    return env


@pytest.fixture
def mock_db(tmp_path):
    """Create a temp DB file and patch settings.db_path."""
    db_file = tmp_path / "test.db"
    db_file.write_text("")  # ensure parent exists
    with patch("raven.cli.main.settings.db_path", str(db_file)):
        yield db_file


class TestCliRoot:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code in (0, 2)

    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output


class TestCliStatus:
    def test_status_offline(self, runner):
        result = runner.invoke(cli, ["status"])
        assert isinstance(result.output, str)

    def test_status_running(self, runner, mock_db):
        with patch("raven.cli.main.Path.exists", return_value=True):
            with patch("raven.cli.main.Path.read_text", return_value="12345"):
                result = runner.invoke(cli, ["status"])
                assert isinstance(result.output, str)


class TestCliDoctor:
    def test_doctor_basic(self, runner, mock_db):
        with patch("raven.cli.main.Path.exists", return_value=True):
            with patch("raven.cli.main.Path.read_text", return_value='{"model": "test"}'):
                result = runner.invoke(cli, ["doctor"])
                assert result.exit_code == 0
                # every posture helper has to reach the printed table, or it is a dead control
                assert "Admin Accounts" in result.output

    def test_doctor_no_config(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "DB Path" in result.output

    def test_the_doctor_names_the_files_a_start_reads(self, runner, _a_command_adopts_only_this_run):
        result = runner.invoke(cli, ["doctor"])
        assert "Env Files" in result.output
        # the table cell is narrower than a pytest temp path, so rich breaks the name at its hyphens
        assert _a_command_adopts_only_this_run.name in "".join(result.output.split())

    def test_a_channel_only_a_file_configures_is_reported_as_configured(
        self, runner, _a_command_adopts_only_this_run, pin_env_names
    ):
        """The row used to answer from this process's exports only.

        Measured 2026-11-14: with ``TELEGRAM_BOT_TOKEN`` in the file its own ``Settings`` had read, a fresh
        ``raven doctor`` printed ``Channels … None configured`` — the report told the operator to go and
        configure the channel that was already configured.
        """
        _a_command_adopts_only_this_run.write_text("TELEGRAM_BOT_TOKEN=123456:SENTINEL\n", encoding="utf-8")
        pin_env_names(["TELEGRAM_BOT_TOKEN"])
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "telegram" in result.output


class TestCliService:
    def test_service_help(self, runner):
        result = runner.invoke(cli, ["service", "--help"])
        assert result.exit_code == 0

    def test_service_status_no_service(self, runner):
        with patch("raven.cli.service.Path.exists", return_value=False):
            result = runner.invoke(cli, ["service", "status"])
            assert result.exit_code == 0


class TestStartDaemonHint:
    def test_windows_names_the_command_that_registers_the_service(self, runner):
        # Before wave #117 the only Windows answer was a systemd/launchd tip, so `raven start
        # --daemon` printed two paths a Windows box cannot use and started nothing.
        with patch("raven.cli.main.IS_WINDOWS", True):
            result = runner.invoke(cli, ["start", "--daemon"])
        assert result.exit_code == 0
        assert "raven service install" in result.output
        assert "systemd" not in result.output
        assert "launchd" not in result.output

    def test_other_platforms_name_deploy_files_that_exist(self, runner):
        root = Path(__file__).resolve().parent.parent
        with patch("raven.cli.main.IS_WINDOWS", False):
            result = runner.invoke(cli, ["start", "--daemon"])
        assert (root / "deploy" / "raven.service").is_file()
        assert (root / "deploy" / "com.raven.plist").is_file()
        assert "deploy/raven.service" in result.output
        assert "raven service install" not in result.output


class TestCliPlugins:
    def test_plugins_list(self, runner, mock_db):
        with patch("raven.cli.main.Path.iterdir", return_value=[]):
            result = runner.invoke(cli, ["plugins", "list"])
            assert "No" in result.output or "plugin" in result.output


class TestCliModels:
    def test_models_list(self, runner, mock_db):
        with patch("raven.cli.main.Path.exists", return_value=True):
            result = runner.invoke(cli, ["models", "list"])
            assert result.exit_code == 0


class TestCliDb:
    def test_db_version(self, runner, mock_db):
        result = runner.invoke(cli, ["db", "version"])
        assert result.exit_code == 0


class TestCliUpdate:
    def test_update_dry(self, runner):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="0.4.0")):
            with patch("raven.cli.main.Path.exists", return_value=True):
                result = runner.invoke(cli, ["update", "--dry-run"])
                assert result.exit_code in (0, 1)


class TestCliHistory:
    def test_history_exists(self, runner, mock_db):
        result = runner.invoke(cli, ["history"])
        assert result.exit_code in (0, 2)


class TestCliAgent:
    def test_agent_help(self, runner):
        result = runner.invoke(cli, ["agent", "--help"])
        assert result.exit_code == 0


class TestCliSecurity:
    def test_security_audit(self, runner, mock_db):
        with patch("raven.core.security.security_audit.SecurityAudit") as MockAudit:
            mock_instance = MockAudit.return_value
            mock_instance.run_all_checks.return_value = []
            result = runner.invoke(cli, ["security", "audit"])
            assert result.exit_code == 0


class TestCliTui:
    def test_tui_help(self, runner):
        result = runner.invoke(cli, ["tui", "--help"])
        assert result.exit_code == 0


class TestCliPairing:
    def test_pairing_list(self, runner, mock_db):
        result = runner.invoke(cli, ["pairing", "list"])
        assert result.exit_code == 0

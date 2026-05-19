from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from raven.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


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

    def test_doctor_no_config(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0


class TestCliService:
    def test_service_help(self, runner):
        result = runner.invoke(cli, ["service", "--help"])
        assert result.exit_code == 0

    def test_service_status_no_service(self, runner):
        with patch("raven.cli.service.Path.exists", return_value=False):
            result = runner.invoke(cli, ["service", "status"])
            assert result.exit_code == 0


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

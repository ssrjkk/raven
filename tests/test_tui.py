from __future__ import annotations

from click.testing import CliRunner

from raven.cli.main import cli


def test_tui_module_importable():
    from raven.tui.app import RavenTUI, DashboardScreen, LogWidget

    assert RavenTUI.TITLE == "Raven AI"
    assert DashboardScreen is not None
    assert LogWidget is not None


def test_tui_cli_command_exists():
    runner = CliRunner()
    result = runner.invoke(cli, ["tui", "--help"])
    assert result.exit_code == 0
    assert "TUI" in result.output


def test_raven_tui_app_class():
    from raven.tui.app import RavenTUI

    app = RavenTUI()
    assert app.TITLE == "Raven AI"

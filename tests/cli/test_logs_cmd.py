from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from raven.cli.logs_cmd import _render_line, logs

_JSON_LINE = json.dumps(
    {
        "timestamp": "2026-10-19T06:37:02.339793Z",
        "level": "WARNING",
        "module": "raven.channels.telegram",
        "function": "send",
        "line": 42,
        "message": "\u043f\u0440\u0438\u0432\u0435\u0442 [bold]not markup[/bold]",
        "correlation_id": "abc123",
    },
    ensure_ascii=False,
)

_PLAIN_LINE = "2026-10-19 06:37:13.151 | INFO     | raven.core.logging:setup_logging:194 - Logging initialized"


class TestRenderLine:
    def test_json_line_becomes_a_readable_record(self) -> None:
        entry = _render_line(_JSON_LINE)
        assert entry is not None
        level, text = entry
        assert level == "WARNING"
        assert text.startswith("2026-10-19T06:37:02.339793Z | WARNING  | raven.channels.telegram - ")
        assert "[bold]not markup[/bold]" in text
        assert text.endswith("[abc123]")

    def test_legacy_plain_line_is_still_read(self) -> None:
        entry = _render_line(_PLAIN_LINE)
        assert entry is not None
        level, text = entry
        assert level == "INFO"
        assert "Logging initialized" in text

    @pytest.mark.parametrize("line", ["", "   ", "not json at all", '{"level":"NOPE","message":"x"}'])
    def test_lines_without_a_known_level_are_dropped(self, line: str) -> None:
        assert _render_line(line) is None


@pytest.fixture
def _log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from raven.core import config as config_module

    path = tmp_path / "raven.log"
    path.write_text(_JSON_LINE + "\n" + _PLAIN_LINE + "\n", encoding="utf-8")
    monkeypatch.setattr(type(config_module.settings), "resolved_log_file", property(lambda self: path))
    return path


def test_logs_command_renders_the_json_it_writes(_log_file: Path) -> None:
    result = CliRunner().invoke(logs, ["-n", "10"])
    assert result.exit_code == 0, result.output
    assert "WARNING" in result.output
    assert "Logging initialized" in result.output


def test_logs_command_filters_by_level(_log_file: Path) -> None:
    result = CliRunner().invoke(logs, ["-n", "10", "--level", "ERROR"])
    assert result.exit_code == 0, result.output
    assert "Logging initialized" not in result.output


def test_logs_command_does_not_read_the_retired_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from raven.core import config as config_module

    legacy = tmp_path / "legacy.log"
    legacy.write_text(_JSON_LINE + "\n", encoding="utf-8")
    missing = tmp_path / "settings.log"
    monkeypatch.setenv("RAVEN_LOG_FILE", str(legacy))
    monkeypatch.setattr(type(config_module.settings), "resolved_log_file", property(lambda self: missing))
    result = CliRunner().invoke(logs, [])
    assert result.exit_code == 1
    assert "No log file found" in result.output

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_launcher():
    path = Path(__file__).resolve().parents[1] / "scripts" / "launcher.py"
    spec = importlib.util.spec_from_file_location("raven_desktop_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_help_exits_without_starting_the_gateway(monkeypatch, capsys) -> None:
    launcher = _load_launcher()
    monkeypatch.setattr(sys, "argv", ["Raven.exe", "--help"])

    assert launcher.main() == 0
    output = capsys.readouterr().out
    assert "Raven Desktop" in output
    assert "--no-browser" in output
    assert "--ghost" in output

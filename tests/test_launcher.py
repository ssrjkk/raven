from __future__ import annotations

import sys

from scripts import launcher


def test_help_exits_without_starting_the_gateway(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["Raven.exe", "--help"])

    assert launcher.main() == 0
    output = capsys.readouterr().out
    assert "Raven Desktop" in output
    assert "--no-browser" in output
    assert "--ghost" in output

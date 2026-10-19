"""The console and wire encodings are pinned, not inherited from the machine code page.

Measured on a cp1251 host: `console.print()` of the glyph `✓` — which `ravencode/cli/tui.py` puts
in the title of every result panel — raises `UnicodeEncodeError` out of rich's `_check_buffer`, the
command exits 1 and prints nothing at all. The same call after `use_utf8_console()` writes the
character. `raven/cli/main.py` carried that pin inline and `raven/core/mcp/server.py` carried
another copy; both now call the same helpers, and the CLI that had no copy is covered too.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from raven.core.stdio import use_utf8_console, use_utf8_stdio

ROOT = Path(__file__).resolve().parents[2]
_CHECK = "\u2713"  # ✓, spelled so the source encoding cannot matter


def _run(child: str, encoding: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONIOENCODING": encoding, "PYTHONPATH": str(ROOT), "LOGURU_LEVEL": "ERROR"},
        input="",
        check=False,
    )


def _child(*, pin: str) -> str:
    return textwrap.dedent(
        f"""
        import sys
        {pin}
        sys.stdout.write("{_CHECK} \\u043f\\u0440\\u0438\\u0432\\u0435\\u0442 \\u5185\\u5bb9")
        sys.stdout.flush()
        """
    )


@pytest.mark.parametrize("encoding", ["cp1251", "ascii"])
def test_unpinned_output_dies_on_a_console_that_cannot_encode_it(encoding: str) -> None:
    """The negative control: without the pin the process exits 1 with empty output."""
    proc = _run(_child(pin=""), encoding)
    assert proc.returncode != 0
    assert "UnicodeEncodeError" in proc.stderr
    assert proc.stdout == ""


@pytest.mark.parametrize("encoding", ["cp1251", "ascii"])
def test_console_pin_lets_the_same_text_through(encoding: str) -> None:
    proc = _run(_child(pin="from raven.core.stdio import use_utf8_console; use_utf8_console()"), encoding)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout == "\u2713 \u043f\u0440\u0438\u0432\u0435\u0442 \u5185\u5bb9"


def test_stdio_pin_covers_stdin_too() -> None:
    """The MCP transport reads the host's frames, so stdin has to be UTF-8 as well."""
    child = textwrap.dedent(
        """
        import json, sys
        from raven.core.stdio import use_utf8_console, use_utf8_stdio
        before = sys.stdin.encoding
        use_utf8_stdio()
        print(json.dumps({"before": before, "after": sys.stdin.encoding, "out": sys.stdout.encoding}))
        """
    )
    proc = _run(child, "cp1251")
    assert proc.returncode == 0, proc.stderr[-2000:]
    observed = json.loads(proc.stdout.strip())
    assert observed["before"].lower() == "cp1251"
    assert observed["after"] == "utf-8"
    assert observed["out"] == "utf-8"


def test_pin_survives_streams_without_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A replaced stream (a test capture, a redirected pipe object) must not break setup."""
    class Legacy:
        def write(self, text: str) -> int:
            return len(text)

    monkeypatch.setattr(sys, "stdout", Legacy())
    monkeypatch.setattr(sys, "stderr", Legacy())
    monkeypatch.setattr(sys, "stdin", object())
    use_utf8_console()
    use_utf8_stdio()


def test_both_clis_apply_a_pin() -> None:
    """The pin lives in one module, but each front door has to actually call it."""
    for relative in ("raven/cli/main.py", "ravencode/cli/main.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "use_utf8_console()" in source, relative
    for relative in ("raven/core/mcp/__main__.py", "ravencode/mcp/__main__.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "use_utf8_stdio()" in source, relative

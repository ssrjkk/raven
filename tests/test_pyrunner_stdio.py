"""The sandbox subprocess runner must read and write UTF-8 whatever code page the host uses.

`raven.tools.shell.python_code`, `raven/plugins/code` and `raven/plugins/process` all spawn
`python -m raven.tools._pyrunner`, write `code.encode("utf-8")` into it and decode UTF-8 back.
Before the runner pinned its own streams it used the machine's ANSI code page in between: on a
cp1251 host `len("привет")` executed as `len` of mojibake and returned 12, and an emoji result
killed the child with UnicodeEncodeError, so the tool answer was a traceback.
"""

from __future__ import annotations

import pytest

from raven.tools.shell import python_code

_CASES = [
    pytest.param('len("привет")', "6", id="cyrillic-source-is-decoded-as-utf-8"),
    pytest.param('"ключ 内容" + "-tail"', "ключ 内容-tail", id="cyrillic-and-cjk-result-survives"),
    pytest.param('chr(128055) + " ready"', "🐷 ready", id="emoji-result-does-not-crash-the-child"),
    pytest.param('"hello".upper()', "HELLO", id="ascii-still-works"),
]


@pytest.mark.slow
@pytest.mark.parametrize("code,expected", _CASES)
async def test_python_tool_serves_utf8_on_a_cp1251_host(
    code: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    assert await python_code(code) == expected

"""A subprocess reading another program's output must say in which encoding it arrives.

`text=True` without `encoding=` decodes with `locale.getpreferredencoding(False)` — cp1251 on a
Russian Windows, ascii under a POSIX `C` locale. Git and ripgrep write UTF-8, so the read is wrong
either way: `Ё` (UTF-8 `d0 81`) comes back through cp1251 as `РЃ`, because that codec maps `0x81` to
U+0403 rather than to the byte's UTF-8 partner, and the same bytes against an ascii codec raise
`UnicodeDecodeError: 'ascii' codec can't decode byte 0xd0`. The guard below keeps the next `text=True`
call from reintroducing that.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

import pytest

from raven.coding.git_integration import GitIntegration

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = ("raven", "ravencode", "aios", "scripts")
SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _is_subprocess_call(node: ast.Call) -> bool:
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return isinstance(fn.value, ast.Name) and fn.value.id == "subprocess" and fn.attr in SUBPROCESS_FUNCS
    return isinstance(fn, ast.Name) and fn.id in SUBPROCESS_FUNCS


def unpinned_text_mode_calls(source: str) -> list[int]:
    """Line numbers of subprocess calls that ask for str output but never name an encoding."""
    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
            continue
        kwargs = {k.arg: k for k in node.keywords if k.arg}
        text_mode = kwargs.get("text") or kwargs.get("universal_newlines")
        if text_mode is None or "encoding" in kwargs:
            continue
        if isinstance(text_mode.value, ast.Constant) and text_mode.value.value is False:
            continue
        offenders.append(node.lineno)
    return offenders


@pytest.mark.parametrize("package", SRC_DIRS)
def test_no_text_mode_subprocess_call_leaves_the_encoding_to_the_locale(package: str) -> None:
    offenders: list[str] = []
    for py in sorted((ROOT / package).rglob("*.py")):
        found = unpinned_text_mode_calls(py.read_text(encoding="utf-8-sig"))
        offenders.extend(f"{py.relative_to(ROOT)}:{line}" for line in found)
    assert offenders == []


def test_the_guard_detects_the_pattern_it_forbids() -> None:
    source = "\n".join(
        [
            "import subprocess",
            'subprocess.run(["git", "log"], capture_output=True, text=True)',
            'subprocess.run(["git", "log"], capture_output=True, text=True, encoding="utf-8")',
            'subprocess.run(["git", "log"], capture_output=True)',
            'subprocess.Popen(["rg"], universal_newlines=True)',
        ]
    )
    assert unpinned_text_mode_calls(source) == [2, 5]


def _git(repo: Path, *args: str) -> Any:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def test_git_output_arrives_decoded_as_utf8(tmp_path: Path) -> None:
    message = "фикс: Ёж и 内容 в сообщении"
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "ssrjkk@example.com")
    _git(tmp_path, "config", "user.name", "Sergey Sitnikov")
    (tmp_path / "ключ.txt").write_text("данные\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", message)

    gi = GitIntegration(tmp_path)
    subject, _ = gi._run("log", "-1", "--pretty=%s")
    assert subject == message

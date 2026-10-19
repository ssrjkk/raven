"""A file written in UTF-8 has to be read back in UTF-8, whatever the host locale says.

`open()`, `Path.open()`, `read_text()` and `write_text()` without `encoding=` use
`locale.getpreferredencoding(False)` — cp1251 on a Russian Windows, ANSI_X3.4-1968 under a POSIX `C`
locale. Raven's own writers do not follow that: `raven/core/_json.py` serialises with orjson, which
emits raw UTF-8 instead of ASCII escapes, and several writers already state `encoding="utf-8"`. When
the reader disagrees with the writer the audit trail is the first thing to show it, because a
mis-decoded line no longer hashes to the value stored next to it — see
`test_audit_chain_verifies_a_non_ascii_entry`.

The AST guard is the part that works everywhere; the in-process test bites on a host whose default is
not UTF-8, and the subprocess test forces the default off so it bites on any runner.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC_DIRS = ("raven", "ravencode", "aios", "scripts")
FILE_METHODS = {"open", "read_text", "write_text"}
# Objects that expose .open() but are not paths: they take no text encoding, or a different one.
FOREIGN_RECEIVERS = {
    "Image", "PILImage", "webbrowser", "os", "io", "socket", "shutil", "tempfile",
    "aiofiles", "wave", "gzip", "bz2", "lzma", "zipfile", "zf", "zip", "tarfile",
}


def _receiver_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return value.func.id
    return ""


def unpinned_text_io_calls(source: str) -> list[int]:
    """Line numbers of file reads/writes that leave the encoding to the locale."""
    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            name, mode_arg, encoding_positional = fn.id, (node.args[1] if len(node.args) > 1 else None), False
            if name != "open":
                continue
        elif isinstance(fn, ast.Attribute) and fn.attr in FILE_METHODS:
            if _receiver_name(fn.value) in FOREIGN_RECEIVERS:
                continue
            name = fn.attr
            mode_arg = node.args[0] if name == "open" and node.args else None
            # read_text(encoding=...) accepts the encoding positionally; write_text's first
            # positional is the content, so it never counts as an encoding.
            encoding_positional = bool(node.args) and name == "read_text"
        else:
            continue
        if encoding_positional or any(k.arg == "encoding" for k in node.keywords):
            continue
        mode = mode_arg.value if isinstance(mode_arg, ast.Constant) else None
        if isinstance(mode, str) and "b" in mode:
            continue
        offenders.append(node.lineno)
    return offenders


@pytest.mark.parametrize("package", SRC_DIRS)
def test_no_text_file_io_leaves_the_encoding_to_the_locale(package: str) -> None:
    offenders: list[str] = []
    for py in sorted((ROOT / package).rglob("*.py")):
        found = unpinned_text_io_calls(py.read_text(encoding="utf-8-sig"))
        offenders.extend(f"{py.relative_to(ROOT)}:{line}" for line in found)
    assert offenders == []


def test_the_guard_detects_the_pattern_it_forbids() -> None:
    source = "\n".join(
        [
            "from pathlib import Path",
            "open(p)",  # offender: text mode, no encoding
            "p.read_text()",  # offender
            "p.write_text(body)",  # offender: write_text's positional is the content
            "Path(p).open('w')",  # offender
            "open(p, 'rb')",  # binary
            "p.open(encoding='utf-8')",
            "p.read_text('utf-8')",  # encoding given positionally
            "Image.open(buf)",
            "aiofiles.open(p, 'rb')",
            "wave.open(p, 'wb')",
        ]
    )
    assert unpinned_text_io_calls(source) == [2, 3, 4, 5]


_NON_ASCII_ACTOR = "@\\u043a\\u043b\\u044e\\u0447"  # @ключ, spelled so argv encoding cannot matter
_NON_ASCII_TEXT = "\\u043f\\u0440\\u0438\\u0432\\u0435\\u0442 \\u0435\\u0451\\u0436 \\u5185\\u5bb9 \\U0001f680"


def _audit_child(tmp_dir: str) -> str:
    return textwrap.dedent(
        f"""
        import asyncio, json, sys
        from pathlib import Path
        from raven.core.audit import AuditEventType, AuditLogger

        path = Path({tmp_dir!r}) / "audit.log"
        actor = "{_NON_ASCII_ACTOR}"
        text = "{_NON_ASCII_TEXT}"

        async def main():
            audit = AuditLogger(str(path), signing_key=b"0" * 32)
            audit.start()
            await audit.log(AuditEventType.MESSAGE_RECEIVED, actor=actor, target="user-1",
                            detail={{"text": text}})
            audit._close_file()

            # What the writer really put on disk, decoded by hand: the reference the readers must match.
            on_disk = json.loads(path.read_bytes().decode("utf-8"))
            assert on_disk["actor"] == actor, on_disk["actor"]

            assert audit.verify_chain() == [{{"valid": True, "entries": 1, "lines_scanned": 1}}], audit.verify_chain()
            assert audit.verify_signatures()[0]["valid"] is True, audit.verify_signatures()
            [entry] = audit.recent(5)
            assert entry["actor"] == actor and entry["detail"]["text"] == text, entry
            print("OK", flush=True)

        asyncio.run(main())
        """
    )


def test_audit_chain_verifies_a_non_ascii_entry(tmp_path: Path) -> None:
    """A tamper-evident log must not call its own clean entries tampered."""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", _audit_child(str(tmp_path))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(ROOT),
        env={
            **os.environ,
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
            "LC_ALL": "C",
            "PYTHONPATH": str(ROOT),
            "LOGURU_LEVEL": "ERROR",
        },
        check=False,
    )
    assert "OK" in proc.stdout, f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr[-4000:]}"


def _loguru_child(tmp_dir: str) -> str:
    return textwrap.dedent(
        f"""
        import json, sys
        from pathlib import Path
        from loguru import logger
        from raven.core.logging import setup_logging

        text = "{_NON_ASCII_TEXT}"
        setup_logging(log_file=Path({tmp_dir!r}) / "raven.log")
        logger.info("marker {{}} end", text)
        logger.remove()

        raw = (Path({tmp_dir!r}) / "raven.log").read_bytes()
        record = json.loads(raw.decode("utf-8").strip().splitlines()[-1])
        assert record["message"] == "marker " + text + " end", record
        print("OK", flush=True)
        """
    )


def test_loguru_file_sink_writes_utf8_under_a_c_locale(tmp_path: Path) -> None:
    """`logger.add(path)` inherits the locale too, and orjson puts raw UTF-8 on the wire.

    Without `encoding="utf-8"` on the sink, a `C` locale raises inside the sink and the record never
    reaches the file — the failure is silent for whoever reads the log afterwards.
    """
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", _loguru_child(str(tmp_path))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(ROOT),
        env={
            **os.environ,
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
            "LC_ALL": "C",
            "PYTHONPATH": str(ROOT),
            "LOGURU_LEVEL": "ERROR",
        },
        check=False,
    )
    assert "OK" in proc.stdout, f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr[-4000:]}"

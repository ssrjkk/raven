"""The stdio servers must speak UTF-8 regardless of the code page the machine boots with.

The MCP transport is newline-delimited UTF-8 JSON. Left to itself, a Python child process
encodes stdin/stdout with the locale codec, so these tests force the hostile case: a child
told to use cp1251 must still serve a Russian host.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_CONTENT = "ключ 内容 🚀\n"
_TIMEOUT = 180


def _serve(module: str, workspace: Path, frames: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1251"
    return subprocess.run(
        [sys.executable, "-m", module, "--workspace", str(workspace)],
        input="".join(f"{frame}\n" for frame in frames),
        capture_output=True,
        env=env,
        text=True,
        encoding="utf-8",
        timeout=_TIMEOUT,
    )


def _frames(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


@pytest.mark.slow
@pytest.mark.parametrize("module", ["raven.core.mcp", "ravencode.mcp"])
def test_stdio_server_serves_utf8_on_a_cp1251_machine(module: str, tmp_path: Path) -> None:
    (tmp_path / "ключ.txt").write_text(_CONTENT, encoding="utf-8")
    call = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "read",
                "arguments": {"path": "ключ.txt"},
            },
        }
    )
    # A blank frame in the middle: the loop must skip it and keep serving.
    proc = _serve(module, tmp_path, ['{"jsonrpc":"2.0","id":1,"method":"ping"}', "", call])

    assert proc.returncode == 0, proc.stderr[-2000:]
    responses = _frames(proc.stdout)
    assert [r["id"] for r in responses] == [1, 2]
    assert _CONTENT in responses[1]["result"]["content"][0]["text"]

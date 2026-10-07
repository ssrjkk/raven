"""Manual smoke test for raven-mcp / ravencode-mcp stdio servers."""
from __future__ import annotations

import json
import subprocess
from typing import Any


def probe(cmd: list[str]) -> None:
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=r"D:\raven",
    )
    assert proc.stdin is not None and proc.stdout is not None

    def send(obj: dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def recv() -> dict[str, Any]:
        line = proc.stdout.readline()  # type: ignore[union-attr]
        assert line and line.strip(), "server closed before responding"
        resp: dict[str, Any] = json.loads(line)
        return resp

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                     "clientInfo": {"name": "manual-test", "version": "1.0"}}})
    init = recv()
    print(f"[{cmd[0]}] initialize -> {init['result']['serverInfo']['name']}")

    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = recv()["result"]["tools"]
    print(f"[{cmd[0]}] tools/list -> {len(tools)} tools, first={tools[0]['name']}")

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "read", "arguments": {"path": "README.md", "max_chars": 60}}})
    text = recv()["result"]["content"][0]["text"].replace("\n", " ")[:60]
    print(f"[{cmd[0]}] tools/call read -> {text}")

    send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
          "params": {"name": "read", "arguments": {"path": r"C:\Windows\win.ini"}}})
    text = recv()["result"]["content"][0]["text"].replace("\n", " ")[:60]
    print(f"[{cmd[0]}] outside-workspace -> {text}")

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"[{cmd[0]}] exit={proc.returncode}")


if __name__ == "__main__":
    for server in (["raven-mcp"], ["ravencode-mcp"]):
        probe(server)

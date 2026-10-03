"""Record real MCP frames from raven-mcp and regenerate the landing site data files.

Starts the stdio server, exchanges a fixed set of side-effect-free frames, and writes:
    site/mcp-frames.js    — request/response pairs the browser demo replays
    site/tools-data.js    — the registry as the server reports it, grouped by category

Run from the repo root:  python scripts/record_site_frames.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

CATEGORIES: dict[str, list[str]] = {
    "file": ["read", "write", "edit", "verify", "glob", "grep"],
    "shell": ["bash"],
    "web": [
        "web_search", "web_fetch", "browser_navigate", "browser_click", "browser_type",
        "browser_screenshot", "browser_get_html", "browser_evaluate", "browser_close",
    ],
    "git": ["git_status", "git_diff", "git_log", "git_commit", "git_add"],
    "code": [
        "run_tests", "format_file", "format_files", "smart_edit", "patch", "lsp_completion",
        "lsp_definition", "lsp_references", "lsp_hover", "lsp_diagnostics", "code_search",
    ],
    "agent": ["think", "task", "task_parallel", "memory_remember", "memory_recall", "question"],
    "workflow": [
        "undo", "redo", "checkpoint_save", "checkpoint_restore", "checkpoint_list",
        "undo_changes", "auto_commit", "todowrite", "todolist", "todoupdate", "todoclear",
        "anchored_summary_write", "anchored_summary_append", "anchored_summary_read",
        "anchored_summary_clear",
    ],
    "infra": [
        "sandbox_exec", "sandbox_policy", "create_artifact", "read_image", "canvas_render",
        "nodes_list", "cron_schedule", "cron_list", "cron_cancel", "talk", "skill",
        "download_skill", "set_skill_registry",
    ],
}

FRAMES: list[dict[str, Any]] = [
    {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "raven-landing", "version": "1.0"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
    {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "read", "arguments": {"path": "README.md", "max_chars": 100}},
    },
    {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "glob", "arguments": {"pattern": "docs/*.md", "path": "."}},
    },
    {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {}},
    {"jsonrpc": "2.0", "id": 7, "method": "resources/list", "params": {}},
]


def exchange(cmd: list[str]) -> list[dict[str, Any]]:
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=ROOT,
    )
    if proc.stdin is None or proc.stdout is None:
        raise RuntimeError("server pipes unavailable")

    recorded: list[dict[str, Any]] = []
    for frame in FRAMES:
        proc.stdin.write(json.dumps(frame) + "\n")
        proc.stdin.flush()
        if frame["method"].startswith("notifications/"):
            recorded.append({"request": frame, "response": None})
            continue
        line = proc.stdout.readline()
        if not line.strip():
            raise RuntimeError(f"server closed before answering {frame['method']}")
        recorded.append({"request": frame, "response": json.loads(line)})

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    return recorded


def registry_tools(response: dict[str, Any]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = response["result"]["tools"]
    return tools


def build_entries(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    category_of = {name: category for category, names in CATEGORIES.items() for name in names}
    ungrouped = sorted(t["name"] for t in tools if t["name"] not in category_of)
    if ungrouped:
        raise KeyError(f"tools missing from CATEGORIES: {ungrouped}")
    stale = sorted(set(category_of) - {t["name"] for t in tools})
    if stale:
        raise KeyError(f"CATEGORIES lists tools the registry does not expose: {stale}")

    entries: list[dict[str, Any]] = []
    for tool in tools:
        schema = tool["inputSchema"]
        props: dict[str, Any] = schema.get("properties", {})
        entries.append({
            "name": tool["name"],
            "category": category_of[tool["name"]],
            "description": tool["description"],
            "params": {key: value.get("type", "string") for key, value in props.items()},
            "required": [key for key in schema.get("required", []) if key in props],
        })
    order: dict[str, int] = {}
    for names in CATEGORIES.values():
        for name in names:
            order[name] = len(order)
    entries.sort(key=lambda e: order[e["name"]])
    return entries


def write_tools_data(entries: list[dict[str, Any]]) -> None:
    body = ",\n".join("    " + json.dumps(entry, ensure_ascii=False) for entry in entries)
    text = (
        "// Generated by scripts/record_site_frames.py from `raven-mcp tools/list`.\n"
        "// Do not edit by hand: rerun the script after changing the tool registry.\n"
        f"const TOOLS_DATA = [\n{body}\n];\n"
    )
    (SITE / "tools-data.js").write_text(text, encoding="utf-8")


def write_frames(recorded: list[dict[str, Any]]) -> None:
    payload = {
        "source": "raven-mcp (stdio) — frames exchanged with the real server",
        "frames": recorded,
    }
    body = json.dumps(payload, indent=1, ensure_ascii=False)
    (SITE / "mcp-frames.js").write_text(
        "// Generated by scripts/record_site_frames.py — real request/response frames, not hand-written.\n"
        "// Do not edit by hand: rerun the script after changing the protocol or the tool registry.\n"
        f"const MCP_FRAMES = {body};\n",
        encoding="utf-8",
    )


def main() -> int:
    server = [sys.executable, "-m", "raven.core.mcp", "--workspace", "."]
    recorded = exchange(server)
    listed = next(r["response"] for r in recorded if r["request"]["method"] == "tools/list")
    if listed is None:
        raise RuntimeError("tools/list produced no response")
    entries = build_entries(registry_tools(listed))
    write_tools_data(entries)
    write_frames(recorded)
    print(f"recorded {len(recorded)} frames, {len(entries)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

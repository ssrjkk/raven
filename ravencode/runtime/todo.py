from __future__ import annotations

import time
from typing import Any

_TODO_STORE: dict[str, dict[str, Any]] = {}
_ORDER: list[str] = []


def todo_write(tasks: list[dict[str, str]]) -> str:
    global _TODO_STORE, _ORDER
    now = time.time()
    lines: list[str] = []
    for t in tasks:
        tid = t.get("id", str(len(_ORDER) + 1))
        content = t.get("content", "")
        status = t.get("status", "pending")
        _TODO_STORE[tid] = {"content": content, "status": status, "updated_at": now}
        if tid not in _ORDER:
            _ORDER.append(tid)
        lines.append(f"  [{status}] {tid}: {content}")
    return "\n".join(lines) if lines else "(empty todo list)"


def todo_list(status_filter: str | None = None) -> str:
    lines: list[str] = []
    for tid in _ORDER:
        item = _TODO_STORE.get(tid)
        if item is None:
            continue
        if status_filter and item["status"] != status_filter:
            continue
        lines.append(f"  [{item['status']}] {tid}: {item['content']}")
    if not lines:
        return "(empty todo list)"
    counts = _summarize_todos()
    return "\n".join(lines) + f"\n\n{counts}"


def todo_update(tid: str, status: str = "pending") -> str:
    if tid not in _TODO_STORE:
        return f"[error] todo {tid} not found"
    _TODO_STORE[tid]["status"] = status
    _TODO_STORE[tid]["updated_at"] = time.time()
    item = _TODO_STORE[tid]
    counts = _summarize_todos()
    return f"[{status}] {tid}: {item['content']}\n{counts}"


def todo_clear() -> None:
    _TODO_STORE.clear()
    _ORDER.clear()


def _reset_state() -> None:
    _TODO_STORE.clear()
    _ORDER.clear()


def _summarize_todos() -> str:
    total = len(_TODO_STORE)
    done = sum(1 for v in _TODO_STORE.values() if v["status"] == "completed")
    in_prog = sum(1 for v in _TODO_STORE.values() if v["status"] == "in_progress")
    return f"Progress: {done}/{total} completed, {in_prog} in progress"

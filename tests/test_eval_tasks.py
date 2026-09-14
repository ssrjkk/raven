"""Deterministic validation of the task-eval suite (no LLM involved).

For every TaskSpec:
  1. setup() builds the starting workspace,
  2. the verifier must FAIL on the untouched workspace,
  3. a reference solution is applied (through the real tool layer where
     practical),
  4. the verifier must PASS.

This guarantees the eval suite itself is sound before spending LLM tokens.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from ravencode.runtime.tools import execute_tool
from ravencode.runtime.workspace import set_workspace_root
from tests.eval.tasks import TASKS, TaskSpec


def _ws(path: Path) -> None:
    set_workspace_root(path)


async def _tool(name: str, **args: Any) -> str:
    return await execute_tool(name, args)


_SOLUTIONS: dict[str, Callable[[Path], Awaitable[None]]] = {}


def _solution(
    task_name: str,
) -> Callable[[Callable[[Path], Awaitable[None]]], Callable[[Path], Awaitable[None]]]:
    def register(fn: Callable[[Path], Awaitable[None]]) -> Callable[[Path], Awaitable[None]]:
        _SOLUTIONS[task_name] = fn
        return fn

    return register


@_solution("create_file")
async def _sol_create_file(ws: Path) -> None:
    await _tool("write", path="greeting.txt", content="hello eval")


@_solution("fix_median_bug")
async def _sol_fix_median_bug(ws: Path) -> None:
    await _tool(
        "write",
        path="median.py",
        content=(
            "def median(nums):\n"
            "    s = sorted(nums)\n"
            "    n = len(s)\n"
            "    mid = n // 2\n"
            "    if n % 2 == 1:\n"
            "        return s[mid]\n"
            "    return (s[mid - 1] + s[mid]) / 2\n"
        ),
    )


@_solution("json_edit_preserve")
async def _sol_json_edit(ws: Path) -> None:
    raw = await _tool("read", path="config.json")
    data = json.loads(raw)
    data["retries"] = 5
    await _tool("write", path="config.json", content=json.dumps(data))


@_solution("write_slugify")
async def _sol_write_slugify(ws: Path) -> None:
    await _tool("write", path="helpers.py", content="def slugify(s):\n    return s.lower().replace(' ', '-')\n")


@_solution("append_log")
async def _sol_append_log(ws: Path) -> None:
    text = await _tool("read", path="app.log")
    await _tool("write", path="app.log", content=text.rstrip("\n") + "\nline-3: shutdown\n")


@_solution("csv_total")
async def _sol_csv_total(ws: Path) -> None:
    await _tool("write", path="result.txt", content="250")


@_solution("make_tests_pass")
async def _sol_make_tests_pass(ws: Path) -> None:
    await _tool("write", path="calc.py", content="def add(a, b):\n    return a + b\n")


@_solution("cleanup_junk")
async def _sol_cleanup_junk(ws: Path) -> None:
    (ws / "temp_junk.tmp").unlink()
    for p in (ws / "cache").iterdir():
        p.unlink()
    (ws / "cache").rmdir()


@_solution("docs_append")
async def _sol_docs_append(ws: Path) -> None:
    text = await _tool("read", path="notes.md")
    await _tool("write", path="notes.md", content=text.rstrip("\n") + "\n- item two\n")


@pytest.mark.parametrize("spec", TASKS, ids=[t.name for t in TASKS])
async def test_task_verifier_roundtrip(spec: TaskSpec, tmp_path: Path) -> None:
    assert spec.name in _SOLUTIONS, f"missing reference solution for {spec.name}"
    spec.setup(tmp_path)
    _ws(tmp_path)
    try:
        # negative: untouched workspace must not pass
        early = spec.verify(tmp_path, "")
        assert early, f"{spec.name}: verifier passed on an untouched workspace"

        await _SOLUTIONS[spec.name](tmp_path)

        late = spec.verify(tmp_path, "done")
        assert late == [], f"{spec.name}: verifier rejected a correct solution: {late}"
    finally:
        set_workspace_root(None)

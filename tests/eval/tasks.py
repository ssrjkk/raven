"""Task-style eval cases: ground truth is a workspace state, not answer text.

Every task has a ``setup`` (builds the starting workspace), a natural-language
``prompt`` for the agent, and a ``verifier`` that checks the resulting
filesystem state deterministically (no LLM judgement). This makes regression
measurement objective: either the file exists with the right content / the
script produces the right output, or it does not.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TaskSpec:
    name: str
    prompt: str
    setup: Callable[[Path], None]
    verify: Callable[[Path, str], list[str]]
    category: str = "task"


def _run_python(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# individual tasks
# ---------------------------------------------------------------------------


def _setup_create_file(ws: Path) -> None:
    (ws / "README.md").write_text("demo project\n", encoding="utf-8")


def _verify_create_file(ws: Path, output: str) -> list[str]:
    f = ws / "greeting.txt"
    if not f.exists():
        return ["greeting.txt was not created"]
    if "hello eval" not in f.read_text(encoding="utf-8").lower():
        return ["greeting.txt does not contain 'hello eval'"]
    return []


def _setup_fix_bug(ws: Path) -> None:
    (ws / "median.py").write_text(
        "def median(nums):\n"
        "    nums.sort()\n"
        "    return nums[len(nums) // 2]\n",  # wrong for even-length lists
        encoding="utf-8",
    )
    (ws / "test_median.py").write_text(
        "from median import median\n"
        "def test_even():\n"
        "    assert median([1, 2, 3, 4]) == 2.5\n"
        "def test_odd():\n"
        "    assert median([1, 2, 3]) == 2\n"
        "test_even()\n"
        "test_odd()\n"
        "print('OK')\n",
        encoding="utf-8",
    )


def _verify_fix_bug(ws: Path, output: str) -> list[str]:
    proc = _run_python(ws / "test_median.py")  # plain assert script
    return [] if proc.returncode == 0 else [f"median tests still fail: {proc.stderr[-200:]}"]


def _setup_json_edit(ws: Path) -> None:
    (ws / "config.json").write_text(
        json.dumps({"debug": False, "retries": 3, "name": "svc"}),
        encoding="utf-8",
    )


def _verify_json_edit(ws: Path, output: str) -> list[str]:
    try:
        data = json.loads((ws / "config.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"config.json is not valid JSON: {exc}"]
    errors = []
    if data.get("retries") != 5:
        errors.append(f"retries must be 5, got {data.get('retries')!r}")
    if data.get("name") != "svc":
        errors.append("other keys must be preserved")
    return errors


def _setup_write_function(ws: Path) -> None:
    (ws / "main.py").write_text(
        "from helpers import slugify\n\nprint(slugify('Hello World'))\n",
        encoding="utf-8",
    )


def _verify_write_function(ws: Path, output: str) -> list[str]:
    helpers = ws / "helpers.py"
    if not helpers.exists():
        return ["helpers.py was not created"]
    proc = _run_python(ws / "main.py")
    if proc.returncode != 0:
        return [f"main.py failed: {proc.stderr[-200:]}"]
    if proc.stdout.strip() != "hello-world":
        return [f"slugify produced {proc.stdout.strip()!r}, expected 'hello-world'"]
    return []


def _setup_append_log(ws: Path) -> None:
    (ws / "app.log").write_text("line-1\nline-2\n", encoding="utf-8")


def _verify_append_log(ws: Path, output: str) -> list[str]:
    lines = (ws / "app.log").read_text(encoding="utf-8").splitlines()
    if lines[:2] != ["line-1", "line-2"]:
        return ["existing log lines were modified or removed"]
    if len(lines) < 3 or "shutdown" not in lines[-1].lower():
        return ["no shutdown entry appended"]
    return []


def _setup_csv_sum(ws: Path) -> None:
    (ws / "sales.csv").write_text(
        "region,amount\nwest,120\neast,80\nwest,50\n", encoding="utf-8"
    )


def _verify_csv_sum(ws: Path, output: str) -> list[str]:
    f = ws / "result.txt"
    if not f.exists():
        return ["result.txt was not created"]
    if f.read_text(encoding="utf-8").strip() != "250":
        return ["result.txt must contain exactly 250"]
    return []


def _setup_make_tests_pass(ws: Path) -> None:
    (ws / "calc.py").write_text(
        "def add(a, b):\n    return a - b  # bug\n", encoding="utf-8"
    )
    (ws / "test_calc.py").write_text(
        "from calc import add\n\nassert add(2, 3) == 5\nassert add(-1, 1) == 0\nprint('OK')\n",
        encoding="utf-8",
    )


def _verify_make_tests_pass(ws: Path, output: str) -> list[str]:
    proc = _run_python(ws / "test_calc.py")
    if proc.returncode != 0:
        return [f"test_calc still failing: {proc.stderr[-200:]}"]
    if "OK" not in proc.stdout:
        return ["test_calc did not print OK"]
    return []


def _setup_cleanup(ws: Path) -> None:
    (ws / "keep.txt").write_text("keep\n", encoding="utf-8")
    (ws / "temp_junk.tmp").write_text("junk\n", encoding="utf-8")
    (ws / "cache").mkdir()
    (ws / "cache" / "old.bin").write_bytes(b"\x00\x01")


def _verify_cleanup(ws: Path, output: str) -> list[str]:
    errors = []
    if not (ws / "keep.txt").exists():
        errors.append("keep.txt must survive")
    if (ws / "temp_junk.tmp").exists():
        errors.append("temp_junk.tmp still exists")
    if (ws / "cache").exists():
        errors.append("cache dir still exists")
    return errors


def _setup_docs_touch(ws: Path) -> None:
    (ws / "notes.md").write_text("# Notes\n\n- item one\n", encoding="utf-8")


def _verify_docs_touch(ws: Path, output: str) -> list[str]:
    text = (ws / "notes.md").read_text(encoding="utf-8")
    if "- item one" not in text:
        return ["original notes content lost"]
    if "- item two" not in text:
        return ["'- item two' was not added"]
    return []


TASKS: list[TaskSpec] = [
    TaskSpec(
        name="create_file",
        prompt="Create a file greeting.txt containing exactly: hello eval",
        setup=_setup_create_file,
        verify=_verify_create_file,
    ),
    TaskSpec(
        name="fix_median_bug",
        prompt=(
            "median.py has a bug: median of an even-length list is wrong. "
            "Fix it so that test_median.py in this directory passes."
        ),
        setup=_setup_fix_bug,
        verify=_verify_fix_bug,
    ),
    TaskSpec(
        name="json_edit_preserve",
        prompt="In config.json change the value of retries to 5. Keep every other key unchanged.",
        setup=_setup_json_edit,
        verify=_verify_json_edit,
    ),
    TaskSpec(
        name="write_slugify",
        prompt=(
            "Create helpers.py with a function slugify(s) that lowercases text and "
            "replaces spaces with dashes, so main.py prints hello-world."
        ),
        setup=_setup_write_function,
        verify=_verify_write_function,
    ),
    TaskSpec(
        name="append_log",
        prompt="Append a new line 'line-3: shutdown' to app.log without changing existing lines.",
        setup=_setup_append_log,
        verify=_verify_append_log,
    ),
    TaskSpec(
        name="csv_total",
        prompt="Compute the sum of the amount column in sales.csv and write just the number to result.txt.",
        setup=_setup_csv_sum,
        verify=_verify_csv_sum,
    ),
    TaskSpec(
        name="make_tests_pass",
        prompt="test_calc.py fails. Fix calc.py so the test script prints OK.",
        setup=_setup_make_tests_pass,
        verify=_verify_make_tests_pass,
    ),
    TaskSpec(
        name="cleanup_junk",
        prompt="Delete temp_junk.tmp and the cache directory. Do not touch keep.txt.",
        setup=_setup_cleanup,
        verify=_verify_cleanup,
    ),
    TaskSpec(
        name="docs_append",
        prompt="Add a line '- item two' to the list in notes.md.",
        setup=_setup_docs_touch,
        verify=_verify_docs_touch,
    ),
]


def get_task_cases() -> list[TaskSpec]:
    return list(TASKS)

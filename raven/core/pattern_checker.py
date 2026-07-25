from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from loguru import logger

_PATTERN_LIST = [
    (
        "print-vs-loguru",
        "Use loguru instead of print",
        "warning",
        "Use from loguru import logger instead of print() for production code",
        "Replace print() with logger.info() / logger.warning() / logger.error()",
    ),
    (
        "missing-type-hints",
        "Missing type hints",
        "warning",
        "Function definitions should have type hints for parameters and return values",
        "Add type annotations to function parameters and return type",
    ),
    (
        "bare-except",
        "Bare except clause",
        "error",
        "Except clauses should specify exception type (except Exception:)",
        "Replace bare 'except:' with 'except SomeException:'",
    ),
    (
        "os-path-vs-pathlib",
        "Use pathlib instead of os.path",
        "info",
        "Prefer pathlib.Path over os.path for path manipulation",
        "Replace os.path.join/ exists/ etc. with pathlib.Path methods",
    ),
    (
        "mutable-default-arg",
        "Mutable default argument",
        "error",
        "Using mutable default arguments (list/dict/set) can cause unexpected behaviour",
        "Use None as default and assign inside the function body",
    ),
    (
        "hardcoded-secret",
        "Possible hardcoded secret",
        "error",
        "String literal looks like an API key, token, or password",
        "Move to environment variable or secrets manager",
    ),
    (
        "todo-fixme",
        "TODO / FIXME comment",
        "info",
        "Code contains TODO or FIXME comments that should be addressed",
        "Address the TODO/FIXME or create a task to track it",
    ),
]

_PATTERN_CHECKS: dict[str, Any] = {}


def _register(name: str) -> Callable[[Any], Any]:
    def wrap(fn: Any) -> Any:
        _PATTERN_CHECKS[name] = fn
        return fn

    return wrap


def _make_violation(
    file: Path, line: int, col: int, pid: str, severity: str, message: str, content_line: str, fix_hint: str
) -> dict[str, Any]:
    return {
        "file": str(file),
        "line": line,
        "column": col,
        "pattern_id": pid,
        "severity": severity,
        "message": message,
        "line_content": content_line[:160],
        "fix_hint": fix_hint,
    }


def _get_patterns() -> list[dict[str, Any]]:
    return [
        {"id": pid, "name": name, "severity": sev, "description": desc, "fix_hint": hint, "check": _PATTERN_CHECKS[pid]}
        for pid, name, sev, desc, hint in _PATTERN_LIST
    ]


def create_pattern_checker_router(workspace: str = "") -> APIRouter:
    router = APIRouter(prefix="/api/v1/patterns", tags=["patterns"])
    ws_root = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    @router.get("/checks")
    def list_checks() -> list[dict[str, Any]]:
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "severity": p["severity"],
                "description": p["description"],
                "fix_hint": p["fix_hint"],
            }
            for p in _get_patterns()
        ]

    @router.get("/run")
    async def run_checks(
        file: str = Query("", description="Single file to check"),
        check_ids: str = Query("", description="Comma-separated check IDs (empty = all)"),
        max_files: int = Query(50, ge=1, le=500),
    ):
        patterns = _get_patterns()
        enabled_ids = (
            [c.strip() for c in check_ids.split(",") if c.strip()] if check_ids else [p["id"] for p in patterns]
        )
        checks = [p for p in patterns if p["id"] in enabled_ids]

        if file:
            target = ws_root / file
            if not target.is_file():
                return {"error": f"File not found: {file}", "violations": []}
            files_to_check = [target]
        else:
            files_to_check = _find_python_files(ws_root, max_files)

        all_violations: list[dict[str, Any]] = []
        for f in files_to_check:
            try:
                content = f.read_text("utf-8")
            except OSError:
                continue
            lines = content.split("\n")
            for check in checks:
                try:
                    violations = check["check"](f, content, lines)
                    all_violations.extend(violations)
                except SyntaxError:
                    pass
                except Exception as e:
                    logger.debug("[pattern_checker] error running {} on {}: {}", check["id"], f, e)

        return {
            "files_checked": len(files_to_check),
            "violations": all_violations,
            "total": len(all_violations),
            "by_severity": {
                "error": sum(1 for v in all_violations if v["severity"] == "error"),
                "warning": sum(1 for v in all_violations if v["severity"] == "warning"),
                "info": sum(1 for v in all_violations if v["severity"] == "info"),
            },
        }

    return router


def _find_python_files(root: Path, max_files: int) -> list[Path]:
    result: list[Path] = []
    try:
        for f in root.rglob("*.py"):
            if f.name.startswith("."):
                continue
            if "node_modules" in str(f) or ".venv" in str(f) or "__pycache__" in str(f):
                continue
            result.append(f)
            if len(result) >= max_files:
                break
    except OSError:
        pass
    return result


@_register("print-vs-loguru")
def _check_print_vs_loguru(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    has_loguru_import = "from loguru import logger" in content or "from loguru" in content
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if (
            stripped.startswith("print(")
            and not stripped.startswith("#")
            and not stripped.startswith('"""')
            and not stripped.startswith("'''")
        ):
            violations.append(
                _make_violation(
                    file,
                    i,
                    line.index("print") + 1,
                    "print-vs-loguru",
                    "warning",
                    "Use logger instead of print()",
                    stripped,
                    "Replace with logger.info()"
                    if not has_loguru_import
                    else "Already imported loguru — replace print() with logger.info()",
                )
            )
    return violations


@_register("missing-type-hints")
def _check_type_hints(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            hints_missing = False
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg == "self" or arg.arg == "cls":
                    continue
                if arg.annotation is None:
                    hints_missing = True
                    violations.append(
                        _make_violation(
                            file,
                            node.lineno,
                            node.col_offset + 1,
                            "missing-type-hints",
                            "warning",
                            f"Function '{node.name}' parameter '{arg.arg}' has no type hint",
                            lines[node.lineno - 1],
                            f"Add type annotation: {arg.arg}: <type>",
                        )
                    )
            if node.returns is None and hints_missing is False:
                violations.append(
                    _make_violation(
                        file,
                        node.lineno,
                        node.col_offset + 1,
                        "missing-type-hints",
                        "info",
                        f"Function '{node.name}' has no return type hint",
                        lines[node.lineno - 1],
                        "Add -> ReturnType annotation",
                    )
                )
    return violations


@_register("bare-except")
def _check_bare_except(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            violations.append(
                _make_violation(
                    file,
                    node.lineno,
                    node.col_offset + 1,
                    "bare-except",
                    "error",
                    "Bare except clause catches all exceptions, including SystemExit and KeyboardInterrupt",
                    lines[node.lineno - 1],
                    "Use 'except Exception:' instead of bare 'except:'",
                )
            )
    return violations


@_register("os-path-vs-pathlib")
def _check_os_path(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    os_path_calls = [
        "os.path.join",
        "os.path.exists",
        "os.path.isfile",
        "os.path.isdir",
        "os.path.abspath",
        "os.path.basename",
        "os.path.dirname",
        "os.path.splitext",
    ]
    for i, line in enumerate(lines, 1):
        for call in os_path_calls:
            if call in line and not line.strip().startswith("#"):
                violations.append(
                    _make_violation(
                        file,
                        i,
                        line.index(call) + 1,
                        "os-path-vs-pathlib",
                        "info",
                        f"Use pathlib.Path instead of {call}()",
                        line,
                        f"Replace {call}() with pathlib.Path methods",
                    )
                )
                break
    return violations


@_register("mutable-default-arg")
def _check_mutable_defaults(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations

    mutable_types = (ast.List, ast.Dict, ast.Set)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults + node.args.kw_defaults:
                if default is not None and isinstance(default, mutable_types):
                    violations.append(
                        _make_violation(
                            file,
                            node.lineno,
                            node.col_offset + 1,
                            "mutable-default-arg",
                            "error",
                            f"Mutable default argument in '{node.name}'",
                            lines[node.lineno - 1],
                            "Use None as default and initialize inside function",
                        )
                    )
    return violations


_SECRET_PATTERNS = [
    re.compile(r"(?i)(?:api[_-]?key|secret|token|password|auth[_-]?token)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
    re.compile(r"(?i)sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)pk-[A-Za-z0-9]{20,}"),
]


@_register("hardcoded-secret")
def _check_hardcoded_secrets(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for i, line in enumerate(lines, 1):
        for pat in _SECRET_PATTERNS:
            m = pat.search(line)
            if m:
                violations.append(
                    _make_violation(
                        file,
                        i,
                        m.start() + 1,
                        "hardcoded-secret",
                        "error",
                        "Possible hardcoded secret/API key",
                        line,
                        "Move to environment variable (.env file or secrets manager)",
                    )
                )
                break
    return violations


@_register("todo-fixme")
def _check_todo_comments(file: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    pat = re.compile(r"#\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
    for i, line in enumerate(lines, 1):
        m = pat.search(line)
        if m:
            tag = m.group(1).upper()
            violations.append(
                _make_violation(
                    file,
                    i,
                    line.index("#") + 1,
                    "todo-fixme",
                    "info",
                    f"{tag} comment in code",
                    line,
                    f"Address the {tag} or create a tracked task",
                )
            )
    return violations

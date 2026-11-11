from __future__ import annotations

import ast
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

DENIED_MODULES = frozenset(
    {
        "os",
        "subprocess",
        "sys",
        "shutil",
        "ctypes",
        "socket",
        "operator",
        "inspect",
        "importlib",
        "pickle",
        "marshal",
        "code",
        "codeop",
        "builtins",
        "typing",
        "pathlib",
        "io",
        "urllib",
        "asyncio",
        "http",
        "threading",
        "multiprocessing",
        "ssl",
        "ftplib",
        "smtplib",
        "poplib",
        "imaplib",
        "telnetlib",
        "sqlite3",
        "select",
        "pty",
        "signal",
        "platform",
        "getpass",
        "pwd",
        "grp",
        "spwd",
        "resource",
        "fcntl",
        "mmap",
        "requests",
        "httpx",
        "aiohttp",
        "urllib3",
    }
)

DENIED_BUILTINS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "type",
        "memoryview",
        "breakpoint",
        "callable",
        "staticmethod",
        "classmethod",
        "property",
        "super",
        "getattr",
        "setattr",
        "delattr",
        "vars",
        "dir",
        "format",
        "format_map",
        "__import__",
        "globals",
        "locals",
    }
)


PYTHON_RUNNER_MODULE = "raven.core._pyrunner"
"""The module every Python-executing surface spawns.

It is spelled once, here, because three call sites build it as a `-m` argument string and nothing in
Python checks such a string.  It sits outside `raven.tools` on purpose: that package's `__init__`
builds the whole tool registry, which measured 13.1 s per sandboxed run against 0.10 s for a bare
interpreter, and the registry's startup log lines came back inside every tool result.
"""

UNTRUSTED_CHILD_ENV_KEYS = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "TZ",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
    }
)

RESTRICTED_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "ascii": ascii,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "frozenset": frozenset,
    "hash": hash,
    "hex": hex,
    "int": int,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}


def untrusted_child_env(parent: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of a process that runs untrusted Python: enough to start, nothing worth stealing.

    Passing `dict(os.environ)` hands the child every `*_KEY`, `*_TOKEN` and `*_SECRET` the gateway
    loaded from `.env`. The AST gate keeps well-behaved code from reading them, but the child should
    not depend on that gate holding for the secrets to stay out of reach.

    Keys are compared case-insensitively because Windows environment names are case-insensitive and
    the casing a parent carries is not ours to choose. `code.run_python` once tested a case-sensitive
    membership for "SystemRoot" against a parent that spells it "SYSTEMROOT" and dropped it; Winsock
    resolves its providers out of %SYSTEMROOT%, so the child died at `import asyncio` with WinError
    10106 before reaching a single line of the code it was asked to run.
    """
    source = os.environ if parent is None else parent
    return {key: value for key, value in source.items() if key.upper() in UNTRUSTED_CHILD_ENV_KEYS}


@dataclass(frozen=True)
class CodeIssue:
    """One refusal the sandbox gate would issue, with the line a report can point at."""

    line: int
    message: str


def _module_root(expr: ast.expr) -> str | None:
    node = expr
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def _node_findings(node: ast.AST) -> list[CodeIssue]:
    findings: list[CodeIssue] = []
    line = getattr(node, "lineno", 0)

    def add(message: str) -> None:
        findings.append(CodeIssue(line=line, message=message))

    if isinstance(node, ast.Name) and node.id in ("__builtins__", "__import__"):
        add(f"access to '{node.id}' is not allowed")
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("__")
        and node.value.endswith("__")
    ):
        add(f"dunder string literal '{node.value}' is not allowed")
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in DENIED_BUILTINS:
            add(f"use of '{func.id}' is not allowed")
        if isinstance(func, ast.Attribute):
            if func.attr in DENIED_BUILTINS:
                add(f"'{func.attr}' called via attribute access")
            root = _module_root(func.value)
            if root is not None and root in DENIED_MODULES:
                add(f"'{root}' module access is not allowed")
    if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
        add(f"dunder attribute '{node.attr}' is not allowed")
    if isinstance(node, ast.Import):
        for alias in node.names:
            module_name = alias.name.split(".")[0]
            if module_name in DENIED_MODULES:
                add(f"import of '{alias.name}' is not allowed")
    if isinstance(node, ast.ImportFrom):
        module_name = (node.module or "").split(".")[0]
        if module_name in DENIED_MODULES:
            add(f"import of '{node.module}' is not allowed")
    return findings


def python_code_issues(code: str) -> list[CodeIssue]:
    """Every refusal this source would earn from the sandbox gate, in AST order.

    A scanner that keeps its own weaker list of "dangerous" constructs drifts away from what actually
    runs: `code.find_issues` missed bare `eval()` while this gate refused it, and still pronounced
    clean the source the runner would deny. Reporting is now a view of the same walk, so the verdict
    and the report cannot disagree.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [CodeIssue(line=e.lineno or 1, message=f"Syntax Error: {e}")]
    findings: list[CodeIssue] = []
    for node in ast.walk(tree):
        findings.extend(_node_findings(node))
    return findings


def validate_python_code(code: str) -> str | None:
    """Return a denial message when the code is unsafe, None otherwise.

    Shared AST gate for every Python code-execution surface (shell 'python'
    tool, in-memory sandbox, and the '_pyrunner' subprocess worker).  The
    message strings are stable: callers prefix them with '[denied]'.  Returns
    only the first refusal, which is all an executor needs; reporters that
    want the whole list call python_code_issues.
    """
    findings = python_code_issues(code)
    return findings[0].message if findings else None

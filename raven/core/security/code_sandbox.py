from __future__ import annotations

import ast

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


def _module_root(expr: ast.expr) -> str | None:
    node = expr
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None


def validate_python_code(code: str) -> str | None:
    """Return a denial message when the code is unsafe, None otherwise.

    Shared AST gate for every Python code-execution surface (shell 'python'
    tool, in-memory sandbox, and the '_pyrunner' subprocess worker).  The
    message strings are stable: callers prefix them with '[denied]'.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax Error: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in ("__builtins__", "__import__"):
            return f"access to '{node.id}' is not allowed"
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith("__")
            and node.value.endswith("__")
        ):
            return f"dunder string literal '{node.value}' is not allowed"
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DENIED_BUILTINS:
                return f"use of '{func.id}' is not allowed"
            if isinstance(func, ast.Attribute):
                if func.attr in DENIED_BUILTINS:
                    return f"'{func.attr}' called via attribute access"
                root = _module_root(func.value)
                if root is not None and root in DENIED_MODULES:
                    return f"'{root}' module access is not allowed"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            return f"dunder attribute '{node.attr}' is not allowed"
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                if module_name in DENIED_MODULES:
                    return f"import of '{alias.name}' is not allowed"
        if isinstance(node, ast.ImportFrom):
            module_name = (node.module or "").split(".")[0]
            if module_name in DENIED_MODULES:
                return f"import of '{node.module}' is not allowed"
    return None

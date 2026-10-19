from __future__ import annotations

import ast
import sys
from typing import cast

from raven.core.security.code_sandbox import validate_python_code
from raven.tools.shell import _RESTRICTED_BUILTINS


def run(code: str) -> str:
    denied = validate_python_code(code)
    if denied is not None:
        return f"[denied] {denied}"
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Syntax Error: {e}"
    last_expr: ast.Expr | None = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last_expr = cast(ast.Expr, tree.body.pop())
    ns: dict[str, object] = {"__builtins__": _RESTRICTED_BUILTINS.copy()}
    exec(compile(tree, "<sandbox>", "exec"), ns)
    if last_expr:
        result = eval(compile(ast.Expression(last_expr.value), "<sandbox>", "eval"), ns)
        return str(result) if result is not None else "(no return value)"
    return "(code executed, no return value)"


if __name__ == "__main__":
    # Callers feed UTF-8 bytes into stdin and decode UTF-8 from stdout; the text streams would
    # insert this machine's ANSI code page in between, exec'ing mojibake and crashing on any
    # result the page cannot encode.
    code = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(run(code).encode("utf-8") + b"\n")

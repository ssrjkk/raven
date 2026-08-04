from __future__ import annotations

import ast
import sys
from typing import cast

from raven.tools.shell import _RESTRICTED_BUILTINS


def run(code: str) -> str:
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
    print(run(sys.stdin.read()))

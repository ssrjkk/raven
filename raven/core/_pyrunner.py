"""The child half of the Python sandbox.

Launched as `python -m raven.core._pyrunner` by every surface that executes Python. It lives outside
`raven.tools` on purpose: importing that package runs its `__init__`, which builds the whole tool
registry — measured at 13.1 s per sandboxed run, against 0.10 s for a bare interpreter, and the
registry's own startup log lines (including where the web secret key file sits) came back in the
`[stderr]` section of every tool result.
"""

from __future__ import annotations

import ast
import sys
from typing import cast

from raven.core.security.code_sandbox import RESTRICTED_BUILTINS, validate_python_code


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
    ns: dict[str, object] = {"__builtins__": RESTRICTED_BUILTINS.copy()}
    exec(
        compile(tree, "<sandbox>", "exec"), ns
    )  # this is the python tool: policy-checked code, run in a child process against RESTRICTED_BUILTINS  # nosec B102
    if last_expr:
        result = eval(
            compile(ast.Expression(last_expr.value), "<sandbox>", "eval"), ns
        )  # the trailing expression of that same checked code, in the same restricted namespace  # nosec B307
        return str(result) if result is not None else "(no return value)"
    return "(code executed, no return value)"


if __name__ == "__main__":
    # Callers feed UTF-8 bytes into stdin and decode UTF-8 from stdout; the text streams would
    # insert this machine's ANSI code page in between, exec'ing mojibake and crashing on any
    # result the page cannot encode.
    code = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    result = run(code).encode("utf-8") + b"\n"
    # The result goes to the binary layer while the code's own `print()` sits in the text layer,
    # which is block-buffered whenever stdout is a pipe. Written as-is, the value arrived before the
    # output that produced it -- `42\nhi` for a program that printed `hi` then evaluated 42 -- unless
    # the caller happened to set PYTHONUNBUFFERED. Flushing first makes the order the code's order.
    sys.stdout.flush()
    sys.stdout.buffer.write(result)
    sys.stdout.buffer.flush()

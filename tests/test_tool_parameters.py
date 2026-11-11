"""A tool's published parameters are a promise to the model.

`ToolRegistry.call` forwards them as `handler(**params)`, so a name the handler does not accept
raises TypeError, and a name it accepts but never reads is silently dropped. Both were shipped:
`dream_cycle` published `engine_ref` with the description "Engine reference (unused)",
`browser_navigate` published `wait_until` while `_page_context` hardcoded `domcontentloaded`, and
`canvas_show` published `width`/`height` it could not apply to a system browser window.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

import pytest

from raven.core.task_engine.tool_registry import ToolRegistry, ToolSpec
from raven.tools.register_all import register_all_tools


@pytest.fixture(scope="module")
def specs() -> list[ToolSpec]:
    return register_all_tools(ToolRegistry()).list()


def _handler_fn(handler: Any) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


def _read_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def _accepts_any_keyword(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if fn.args.kwarg is None:
        return False
    # **kwargs only hides a name if the body forwards it; a bare **kwargs that is never touched
    # drops every argument just as silently as a missing parameter.
    return fn.args.kwarg.arg in _read_names(fn)


def test_the_registry_is_not_empty(specs: list[ToolSpec]) -> None:
    assert len(specs) >= 100
    assert sum(len(s.parameters) for s in specs) >= 300


def test_every_published_parameter_is_accepted_by_the_handler(specs: list[ToolSpec]) -> None:
    broken = []
    for spec in specs:
        fn = _handler_fn(spec.handler)
        accepted = {a.arg for a in list(fn.args.args) + list(fn.args.posonlyargs) + list(fn.args.kwonlyargs)}
        for name in spec.parameters:
            if name not in accepted and not _accepts_any_keyword(fn):
                broken.append(f"{spec.name}.{name}")
    assert not broken, f"published parameters the handler cannot accept: {broken}"


def test_every_published_parameter_is_read_by_the_handler(specs: list[ToolSpec]) -> None:
    unread = []
    for spec in specs:
        fn = _handler_fn(spec.handler)
        read = _read_names(fn)
        opaque = "locals" in read or _accepts_any_keyword(fn)
        for name in spec.parameters:
            if name not in read and not opaque:
                unread.append(f"{spec.name}.{name}")
    assert not unread, f"published parameters the handler never reads: {unread}"


def test_no_schema_admits_a_parameter_does_nothing(specs: list[ToolSpec]) -> None:
    lies = []
    for spec in specs:
        for name, schema in spec.parameters.items():
            description = str(schema.get("description", "")).lower()
            if "unused" in description or "ignored" in description or "no-op" in description:
                lies.append(f"{spec.name}.{name}: {schema.get('description')}")
    assert not lies, f"parameters published as inert: {lies}"

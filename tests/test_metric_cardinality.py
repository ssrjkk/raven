"""A metrics label must come from a bounded domain, not from the traffic.

`MetricsCollector` keys each series by `name{k=v,...}` and never forgets one, so a label value that
varies per request turns a fixed set of counters into a per-session (or per-address) table that grows
until the process dies. Measured on the tree before this gate existed: 76 labelled call sites over 15
key names, two of which were identifiers — `{"ip": client_ip}` on `http_rate_limited` (one series per
visitor, on the very counter a flood trips hardest) and `{"session_id": session_id}` on three
`context_window_*` sites (one series per chat).

The `path` rule is scope-aware because a route label is only safe after `sanitize_metric_path()` has
collapsed its ids, and the two HTTP middleware sites pass it through a local name.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTION_DIRS = ("raven", "aios", "ravencode")
COLLECTOR_METHODS = frozenset({"inc", "observe", "error"})

# A value with one element per thing a caller controls is not a label, it is a leak.
IDENTIFIER_KEYS = frozenset(
    {
        "ip",
        "client_ip",
        "peer",
        "session",
        "session_id",
        "user",
        "user_id",
        "chat_id",
        "token",
        "email",
        "phone",
        "username",
        "correlation_id",
        "request_id",
        "trace_id",
        "url",
        "href",
        "hostname",
        "filename",
        "path_raw",
        "query",
        "message",
    }
)


def _call_name(func: ast.expr) -> str | None:
    return getattr(func, "attr", None) or getattr(func, "id", None)


def _labelled_metrics_calls(scope: ast.AST) -> list[ast.Call]:
    found: list[ast.Call] = []
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call) or _call_name(node.func) not in COLLECTOR_METHODS:
            continue
        if len(node.args) >= 2 and isinstance(node.args[-1], ast.Dict):
            found.append(node)
    return found


def _sanitized_names(scope: ast.AST) -> set[str]:
    """Names this scope assigns from `sanitize_metric_path(...)`."""
    out: set[str] = set()
    for node in ast.walk(scope):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        value = node.value
        if isinstance(value, ast.Call) and _call_name(value.func) == "sanitize_metric_path":
            out.update(t.id for t in targets if isinstance(t, ast.Name))
    return out


def _label_pairs(call: ast.Call) -> Iterator[tuple[str | None, ast.expr]]:
    labels = call.args[-1]
    assert isinstance(labels, ast.Dict)
    for key, value in zip(labels.keys, labels.values, strict=True):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            yield key.value, value
        elif key is None:
            # `{"method": m, **extra}` — whatever `extra` holds is not visible to a static read.
            yield None, value


def _production_scopes() -> Iterator[tuple[str, ast.AST]]:
    for directory in PRODUCTION_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            yield rel, ast.parse(path.read_text(encoding="utf-8", errors="ignore"))


def _all_scopes(tree: ast.AST) -> list[ast.AST]:
    """Every function body plus the module body, so a label is judged against the scope that built it."""
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return [*functions, tree]


def test_no_label_key_names_a_per_caller_identifier() -> None:
    offenders: list[str] = []
    unprovable: list[str] = []
    for rel, tree in _production_scopes():
        for scope in _all_scopes(tree):
            for call in _labelled_metrics_calls(scope):
                for key, value in _label_pairs(call):
                    if key is None:
                        unprovable.append(f"{rel}:{call.lineno} {ast.unparse(value)}")
                    elif key in IDENTIFIER_KEYS:
                        offenders.append(f"{rel}:{call.lineno} {key}")
    assert not unprovable, f"a spread label set hides its keys from this gate: {sorted(set(unprovable))}"
    assert not offenders, f"one Prometheus series per caller: {sorted(set(offenders))}"


def test_a_path_label_is_always_the_sanitized_one() -> None:
    offenders: list[str] = []
    seen: list[str] = []
    for rel, tree in _production_scopes():
        for scope in _all_scopes(tree):
            sanitized = _sanitized_names(scope)
            for call in _labelled_metrics_calls(scope):
                for key, value in _label_pairs(call):
                    if key != "path":
                        continue
                    seen.append(f"{rel}:{call.lineno}")
                    safe = isinstance(value, ast.Call) and _call_name(value.func) == "sanitize_metric_path"
                    safe = safe or (isinstance(value, ast.Name) and value.id in sanitized)
                    if not safe:
                        offenders.append(f"{rel}:{call.lineno} {ast.unparse(value)}")
    assert seen, "the gate stopped finding any path label"
    assert not offenders, f"a raw route label is one series per path id: {sorted(set(offenders))}"


def test_the_scanner_still_sees_the_sites_it_claims_to_cover() -> None:
    """Without this, both gates above could pass green because the AST pattern matched nothing."""
    pairs = 0
    names: set[str] = set()
    for _rel, tree in _production_scopes():
        for scope in _all_scopes(tree):
            for call in _labelled_metrics_calls(scope):
                pairs += sum(1 for _ in _label_pairs(call))
                if isinstance(call.args[0], ast.Constant):
                    names.add(str(call.args[0].value))
    assert pairs >= 40, f"only {pairs} labelled metric pairs scanned — the pattern is broken"
    assert {"http_requests_total", "rate_limiter_blocked", "messages_rate_limited"} <= names, sorted(names)

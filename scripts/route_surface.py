"""The route surface both HTTP servers really serve, and what the write gate makes of each route.

`raven/cli/gateway_runner.py` mounts its routers from locals built inside `_run_gateway`, so a
source scan cannot see the prefixes those routers carry. This builds each one the way the gateway
does and reads the paths off the result. `--check` is what the test suite runs: it fails when a
router is mounted without being audited here, when a write allowance matches nothing, and when a
route a plain account may write comes from a module nobody opened up on purpose.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
from collections.abc import Callable
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi import APIRouter

from raven.core.ab_testing_api import create_ab_testing_router
from raven.core.admin_api import create_admin_router
from raven.core.analytics_api import create_analytics_router
from raven.core.auth.rbac import rbac
from raven.core.browser_api import create_browser_router
from raven.core.chaos_api import create_chaos_router
from raven.core.chat_api import create_chat_router
from raven.core.cicd_api import create_cicd_router
from raven.core.collab_api import create_collab_router
from raven.core.commands_api import create_commands_router
from raven.core.connection_api import create_connection_router
from raven.core.cost_management_api import create_cost_management_router
from raven.core.db import Database
from raven.core.debugger_api import create_debugger_router
from raven.core.dream_api import create_dream_router
from raven.core.email_api import create_email_router
from raven.core.features import FeatureFlags
from raven.core.finetune_api import create_finetune_router
from raven.core.git_api import create_git_router
from raven.core.github_api import create_github_router
from raven.core.insights_api import create_insights_router
from raven.core.kg_api import create_knowledge_router
from raven.core.mcp.http_transport import create_mcp_router
from raven.core.media_api import create_media_router
from raven.core.middleware import (
    _PUBLIC_PATHS,
    DATA_SCOPES,
    MUTATING_METHODS,
    PUBLIC_READ_PREFIXES,
    USER_MUTATING_PERMISSIONS,
    _declared_public,
    _in_data_scope,
    _prefix_match,
    write_permission,
)
from raven.core.ops_api import create_ops_router
from raven.core.pattern_checker import create_pattern_checker_router
from raven.core.plugin_api import create_plugin_router
from raven.core.project_insights_api import create_project_insights_router
from raven.core.project_metrics_api import create_project_metrics_router
from raven.core.rag_api import create_rag_router
from raven.core.scaffold_api import create_scaffold_router
from raven.core.sse_api import create_sse_router
from raven.core.status_api import create_status_router
from raven.core.tests_api import create_tests_router
from raven.core.voice_api import create_voice_router
from raven.core.web_search_api import create_web_search_router
from raven.core.webhooks import create_webhook_router
from raven.core.workflow_api import create_workflow_router
from raven.core.workspace import workspace_root
from raven.gateway.daemon import RavenFlowDaemon

ROOT = pathlib.Path(__file__).resolve().parents[1]
DAEMON_KEY = "raven.gateway.daemon"

# The routers whose writes a plain account is allowed to make, named at their mount site so the
# check below can match them against `gateway_runner.py`. A route under an allowlisted prefix that
# arrives from anywhere else is what this list exists to catch.
EXPOSED_WRITE_ROUTERS = frozenset(
    {
        "webchat.app",
        "get_aios_adapter().get_bridge_router()",
        "collab_router",
        "media_router",
        "commands_router",
        "ops_router",
        "workflow_router",
        "rag_router",
        "knowledge_router",
        "scaffold_router",
        DAEMON_KEY,
    }
)


async def _noop(_message: Any) -> None:
    return None


def _scratch_db() -> Database:
    return Database(pathlib.Path(tempfile.mkdtemp(prefix="raven-route-surface-")) / "routes.db")


def gateway_routers() -> dict[str, Any]:
    """Every router `gateway_runner` mounts, keyed by the expression at its `include_router` site."""
    db = _scratch_db()
    root = str(workspace_root())
    return {
        "webhook_router": create_webhook_router(db, _noop),
        "admin_router": create_admin_router(lambda: {}, lambda: {}, lambda: None),
        "git_router": create_git_router(),
        "github_router": create_github_router(),
        "get_aios_adapter().get_bridge_router()": _bridge_router(),
        "cicd_router": create_cicd_router(),
        "plugin_router": create_plugin_router(),
        "media_router": create_media_router(),
        "debugger_router": create_debugger_router(),
        "knowledge_router": create_knowledge_router(),
        "voice_router": create_voice_router(),
        "collab_router": create_collab_router(),
        "rag_router": create_rag_router(),
        "finetune_router": create_finetune_router(),
        "chaos_router": create_chaos_router(),
        "email_router": create_email_router(),
        "analytics_router": create_analytics_router(),
        "ab_testing_router": create_ab_testing_router(),
        "cost_router": create_cost_management_router(),
        "browser_router": create_browser_router(),
        "web_search_router": create_web_search_router(),
        "workflow_router": create_workflow_router(),
        "commands_router": create_commands_router(),
        "connection_router": create_connection_router(),
        "metrics_router": create_project_metrics_router(),
        "project_insights_router": create_project_insights_router(workspace=root),
        "insights_router": create_insights_router(workspace=root),
        "chat_router": create_chat_router(),
        "scaffold_router": create_scaffold_router(workspace=root),
        "pattern_checker_router": create_pattern_checker_router(workspace=root),
        "create_sse_router()": create_sse_router(),
        "tests_router": create_tests_router(),
        "create_mcp_router()": create_mcp_router(),
        "status_router": create_status_router(None, None, None),  # type: ignore[arg-type]
        "ops_router": create_ops_router(None, FeatureFlags.get()),  # type: ignore[arg-type]
        "dream_router": create_dream_router(None),  # type: ignore[arg-type]
    }


def _bridge_router() -> APIRouter:
    from raven.core.gateway.aios_adapter import get_aios_adapter

    return get_aios_adapter().get_bridge_router()


def _webchat_app() -> APIRouter:
    from raven.channels.webchat.channel import WebChatChannel

    return WebChatChannel(_scratch_db()).app  # type: ignore[return-value]


def mounted_names() -> set[str]:
    """The argument of every `include_router(...)` call in `gateway_runner.py`."""
    source = (ROOT / "raven" / "cli" / "gateway_runner.py").read_text(encoding="utf-8")
    needle = "include_router("
    names: set[str] = set()
    at = source.find(needle)
    while at != -1:
        start = at + len(needle)
        depth, end = 1, start
        while end < len(source) and depth:
            if source[end] == "(":
                depth += 1
            elif source[end] == ")":
                depth -= 1
            end += 1
        arg = source[start : end - 1].strip()
        names.add(arg.split(",")[0].strip())
        at = source.find(needle, end)
    return names


def declared_routes() -> list[tuple[str, str, str]]:
    """`(method, path, owner)` for both servers, owner being the module or mount site behind it."""
    found: list[tuple[str, str, str]] = []
    surfaces: dict[str, Any] = {**gateway_routers(), "webchat.app": _webchat_app()}
    surfaces[DAEMON_KEY] = RavenFlowDaemon(port=0, data_dir=pathlib.Path(tempfile.mkdtemp())).app
    for owner, router in surfaces.items():
        for route in router.routes:
            for method in getattr(route, "methods", None) or set():
                if method != "HEAD":
                    found.append((method, str(route.path), owner))
            if route.__class__.__name__ in ("APIWebSocketRoute", "WebSocketRoute"):
                found.append(("WEBSOCKET", str(route.path), owner))
    return sorted(set(found))


def user_reachable_writes(routes: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    return [
        (method, path, owner)
        for method, path, owner in routes
        if method in MUTATING_METHODS
        and _in_data_scope(path)
        and not _declared_public(path, method)
        and rbac.has_permission("user", write_permission(path))
    ]


def anonymous_reads(routes: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Reads a caller with no credential is answered.

    Derived from the middleware's own predicates rather than restating them, so the audit cannot
    drift from the rule it is supposed to measure. The daemon is left out: it enforces its own
    rule — every path but `/health` needs a credential — and `tests/core/test_write_gates.py`
    proves that over the daemon's whole declared surface.
    """
    out = []
    for method, path, owner in routes:
        if owner == DAEMON_KEY or method in MUTATING_METHODS or method == "WEBSOCKET" or method == "OPTIONS":
            continue
        # Outside the data scopes the middleware delivers files and never reaches a route's data,
        # so those reads are answered to anybody — which is exactly why `check` refuses a new one.
        if path in _PUBLIC_PATHS or not _in_data_scope(path) or _declared_public(path, method):
            out.append((method, path, owner))
    return sorted(set(out))


def check(routes: list[tuple[str, str, str]] | None = None) -> list[str]:
    routes = declared_routes() if routes is None else routes
    failures: list[str] = []

    audited, mounted = set(gateway_routers()) | {"webchat.app"}, mounted_names()
    for missing in sorted(mounted - audited):
        failures.append(f"mounted by the gateway but never audited here: {missing}")
    for stale in sorted(audited - mounted - {"webchat.app"}):
        failures.append(f"audited here but no longer mounted by the gateway: {stale}")

    writes = [r for r in routes if r[0] in MUTATING_METHODS]
    for prefix in sorted(USER_MUTATING_PERMISSIONS):
        if not any(_prefix_match(path, prefix) for _, path, _ in writes):
            failures.append(f"write allowance covers no route: POST/PUT/PATCH/DELETE under {prefix}")

    for method, path, owner in user_reachable_writes(routes):
        if owner not in EXPOSED_WRITE_ROUTERS:
            failures.append(f"{method} {path} is writable by a plain account, mounted by {owner}")

    reads = [r for r in routes if r[0] not in MUTATING_METHODS and r[0] not in ("WEBSOCKET", "OPTIONS")]
    for prefix in sorted(PUBLIC_READ_PREFIXES):
        if not any(_prefix_match(path, prefix) for _, path, _ in reads):
            failures.append(f"public read allowance covers no route: GET under {prefix}")

    for method, path, owner in anonymous_reads(routes):
        # The only non-API path the gateway may answer without a credential is the chat page itself;
        # a second one means a data-bearing namespace was mounted outside `DATA_SCOPES`.
        if not _in_data_scope(path) and path not in _PUBLIC_PATHS and path != "/":
            failures.append(
                f"{method} {path} answers anonymously and sits outside DATA_SCOPES "
                f"{DATA_SCOPES} (mounted by {owner}) — add the namespace to DATA_SCOPES or the route goes"
            )
    return failures


def main(report: Callable[[str], None] = print) -> int:
    routes = declared_routes()
    writes = [r for r in routes if r[0] in MUTATING_METHODS]
    reads = [r for r in routes if r[0] not in MUTATING_METHODS and r[0] not in ("WEBSOCKET", "OPTIONS")]
    report(f"ROUTES {len(routes)} MUTATING {len(writes)} READS {len(reads)}")
    reachable = user_reachable_writes(routes)
    gated = [w for w in writes if not _declared_public(w[1], w[0])]
    report(f"WRITES_OPEN_TO_A_PLAIN_ACCOUNT {len(reachable)}")
    for method, path, owner in reachable:
        report(f"   {method:7} {path:52} {write_permission(path).value:14} {owner}")
    report(f"WRITES_OPERATOR_ONLY {len(gated) - len(reachable)}")
    anon = anonymous_reads(routes)
    report(f"READS_ANSWERED_TO_ANONYMOUS {len(anon)}")
    for method, path, owner in anon:
        report(f"   {method:7} {path:52} {owner}")
    report(f"READS_PRIVATE {len(reads) - len(anon)}")
    failures = check(routes)
    for failure in failures:
        report(f"FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

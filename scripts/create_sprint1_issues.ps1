# Creates the Sprint 1 GitHub issues. Requires: gh auth login (once).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

function New-RavenIssue {
    param(
        [string]$Title,
        [string[]]$BodyLines,
        [string[]]$Labels
    )
    $body = $BodyLines -join "`n"
    $labelArgs = @()
    foreach ($l in $Labels) { $labelArgs += "--label"; $labelArgs += $l }
    $allArgs = @("issue", "create", "--title", $Title, "--body", $body) + $labelArgs
    Write-Host "==> $Title"
    & gh @allArgs --repo "ssrjkk/raven"
}

New-RavenIssue -Title "RAVEN-101: FlowSession persistence + SessionStore + crash recovery" -Labels @("backend", "gateway", "reliability") -BodyLines @(
    "**Sprint 1 · Estimate: 1.5d · Area:** raven/gateway/daemon.py",
    "",
    "`FlowSession` (`raven/gateway/daemon.py:49`) is an in-memory dataclass kept in `self.sessions` (`daemon.py:74`) - all sessions are lost on daemon restart.",
    "",
    "- Add `FlowSession.to_dict()` / `from_dict()` (skip `ReActAgent`/`_task`; keep id, channel, created_at, message_count, status).",
    "- Add `SessionStore` writing JSON per session under `data/sessions/*.json` (path from settings data dir).",
    "- Persist via batched flush every 5s; flush on shutdown.",
    "- On startup scan `data/sessions/`, restore with `status=\"resumed\"`; purge stale entries.",
    "- Graceful shutdown: catch `CancelledError`/`KeyboardInterrupt`, flush, 5s timeout.",
    "",
    "**Acceptance:** session survives restart with `status=resumed`; no loss on Ctrl+C; stale files pruned.",
    "**Tests:** tests/gateway/test_session_store.py (round-trip, recovery, pruning, batched flush).",
    "**Checks:** ruff 0, mypy 0, `python -m pytest tests/gateway/test_session_store.py -q`."
)

New-RavenIssue -Title "RAVEN-102: SSE live session updates to dashboard" -Labels @("backend", "api", "realtime") -BodyLines @(
    "**Sprint 1 · Estimate: 1d · Area:** raven/core/sse.py, raven/gateway/daemon.py, web/src/pages/Dashboard.tsx",
    "",
    "`SessionInfo` (`daemon.py:34`) is never pushed to the UI. SSE infra already exists in `raven/core/sse.py`.",
    "",
    "- Add `GET /events/sessions` SSE endpoint; emit SessionInfo on session create/update/close.",
    "- Wire session events from `RavenFlowDaemon` into the shared SSE hub.",
    "- Frontend: subscribe via `EventSource(\"/events/sessions?token=...\")` in Dashboard, render live session list; close on unmount.",
    "",
    "**Acceptance:** live session list without page reload; no leaked connections on unmount.",
    "**Tests:** tests/core/test_sse.py (event emission, SessionInfo payload, connection close)."
)

New-RavenIssue -Title "RAVEN-103: WS reconnect jitter + unit test" -Labels @("frontend", "realtime") -BodyLines @(
    "**Sprint 1 · Estimate: 0.5d · Area:** web/src/hooks/useWebSocket.ts",
    "",
    "Exponential backoff already exists (`useWebSocket.ts:30`) but has no jitter - synchronized reconnects hammer the gateway.",
    "",
    "- Add +/-30% jitter to the delay at line 30.",
    "- Extract pure function `computeReconnectDelay(attempt, base=1000, cap=30000)` for testability.",
    "",
    "**Acceptance:** delay in [0.85*exp, 1.15*exp], capped at 30s.",
    "**Tests:** web/src/hooks/useWebSocket.test.ts."
)

New-RavenIssue -Title "RAVEN-104: Monitor SLO + alert aggregation + adaptive interval" -Labels @("backend", "monitoring") -BodyLines @(
    "**Sprint 1 · Estimate: 2.5d · Area:** raven/core/monitor/{models,store,engine,alert}.py",
    "",
    "Monitors lack SLO/error-budget, alert aggregation and adaptive polling intervals.",
    "",
    "- `SLO` in models.py: target + window; compute error budget in store.py from monitor_checks history.",
    "- Alert aggregation in alert.py: group by (monitor.group, code) - one root cause = one notification.",
    "- Adaptive interval in engine.py: 3 consecutive failures -> interval x2 (cap 3600s), reset on recovery; expose `effective_interval`.",
    "- `GET /api/monitor/slo` returns per-monitor budget; mark `slo_breached` when exhausted.",
    "",
    "**Acceptance:** budget from history; 10 failing monitors in one group -> 1 notification; interval grows/shrinks.",
    "**Tests:** tests/core/test_monitor_slo.py."
)

New-RavenIssue -Title "RAVEN-105: RAG hybrid search (BM25+cosine) + embedding cache" -Labels @("backend", "rag") -BodyLines @(
    "**Sprint 1 · Estimate: 2d · Area:** raven/core/rag/{retriever,vector_store}.py",
    "",
    "`Retriever.retrieve` (`retriever.py:68`) is semantic-only; vector store has no embedding cache.",
    "",
    "- Hand-rolled BM25 scorer (k1=1.5, b=0.75) in a new bm25.py.",
    "- Hybrid score `w*cosine + (1-w)*bm25` (w=0.7), `search_mode: hybrid|semantic|lexical`.",
    "- Embedding cache `data/cache/embeddings_cache.json` keyed by MD5(chunk); skip re-embedding on re-index.",
    "- Return scores in results.",
    "",
    "**Acceptance:** hybrid ranks exact-term matches higher than semantic (fixture test); re-index of same text calls embedder once; cache persists across runs.",
    "**Tests:** tests/core/test_rag_hybrid.py."
)

New-RavenIssue -Title "RAVEN-106: RBAC at tool level + policy API" -Labels @("backend", "security") -BodyLines @(
    "**Sprint 1 · Estimate: 2d · Area:** raven/core/task_engine/tool_registry.py, raven/tools/*",
    "",
    "Tool execution goes through `_run_handler` (`tool_registry.py:125`); JWT already carries `role` (`daemon.py:98`).",
    "",
    "- `ToolSpec.allowed_roles: list[str] | None`; mark dangerous tools (`db_query` -> admin, `shell` -> admin/developer).",
    "- Enforce in `_run_handler`: denied -> `[error: tool requires role ...]`.",
    "- `GET/POST /api/tools/policy` to view/override role->tool mapping (persist `data/tool_policy.json`).",
    "- Optional Settings.tsx section.",
    "",
    "**Acceptance:** denied tool returns `[error: ...]`, never executes; policy overridable at runtime; default roles preserve current behavior.",
    "**Tests:** tests/core/test_tool_rbac.py."
)

New-RavenIssue -Title "RAVEN-107: raven benchmark CLI (quick win)" -Labels @("cli", "perf") -BodyLines @(
    "**Sprint 1 · Estimate: 1d · Area:** raven/cli/benchmark_cmd.py",
    "",
    "No benchmark command exists yet.",
    "",
    "- `raven/cli/benchmark_cmd.py`: micro-benchmarks for file_read (1MB), shell echo, db_query (SELECT), LLM complete() latency.",
    "- Compute p50/p95/p99 (own percentile impl, no new deps); table output; `--iterations N` (default 20); `--json` for CI.",
    "- Register in `raven/cli/main.py` like init/deploy.",
    "",
    "**Acceptance:** `python -m raven benchmark` works without an LLM key (LLM section skipped with a note); `--json` emits p50/p95/p99.",
    "**Tests:** tests/cli/test_benchmark_cmd.py."
)

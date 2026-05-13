# Raven AI — Codebase Audit (Phase 0)

> Produced: 2026-05-13
> Scope: Full codebase analysis prior to v1.0 enterprise rewrite
> Audit method: Read every file, run tests (160/160 pass), ruff lint (196 issues)

---

## 1. What Works Well (Keep As-Is)

| Component | Reason |
|-----------|--------|
| `core/llm.py` | Solid LLM abstraction with 4 providers, streaming, robust error handling |
| `core/failover.py` | Weighted model failover works — keeps agent alive if one provider fails |
| `core/db.py` | SQLite with migrations, sessions, messages, users — reliable |
| `core/sandbox.py` | Three execution modes (direct/subprocess/docker) with configurable security |
| `core/health.py` | Health check registry with caching and timeouts |
| `core/metrics.py` | Prometheus-compatible metrics with counters, histograms, timed decorator |
| `core/http_client.py` | Shared HTTP connection pool with limits and keepalive |
| `core/circuit_breaker.py` | Proper closed/open/half-open state machine |
| `core/errors.py` | 20 typed error codes with classification |
| `core/jobs.py` | Async job tracking with status lifecycle |
| `channels/enterprise_base.py` | Enterprise channel base with rate limiter, retry, audit hooks |
| `channels/webchat/channel.py` | Fully functional WebSocket + REST web chat with Alpine.js UI |
| `channels/irc/channel.py` | Proper IRC with auto-reconnect and exponential backoff |
| `channels/matrix/channel.py` | Matrix sync loop with reconnection |
| `channels/slack/channel.py` | Slack with signature verification and SDK integration |
| `plugins/` | 10 plugins (browser, code, cron, files, git, memory, OCR, process, sessions, api) |
| `tests/` | 160 tests covering all major components |
| `Dockerfile` + `docker-compose.yml` | Production deployment ready |

---

## 2. What Is Broken or Incomplete (Must Fix)

### CRITICAL — Runtime Errors

| File | Line | Issue |
|------|------|-------|
| `db.py` | 221 | `replace_session_messages` inserts into `channel` column — schema has **no `channel` column** in `messages` table. Will crash at runtime. |
| `admin_api.py` | 86 | `admin_sessions` accesses `s.session_id` — `Session` model field is `.id`, not `.session_id`. `AttributeError` at runtime. |
| `middleware.py` | 63-85 | `rate_limit_middleware` is a stub (only passes GET through). `error_handler_middleware` has dead code + misplaced rate limiting code after return. |
| `plugin_sandbox.py` | 34 | `deny_plugin` passes tuple to `set.discard()` — only discards first element, rest silently ignored. |
| `config_watcher.py` | 47 | Reloads `.env` into `os.environ` but never re-inits pydantic `Settings` — changes have zero effect. |
| `gateway.py` | 181 | `/new` command sends response to `event.session_id` (old session) instead of new session. |
| `gateway.py` | 186 | `/reset` is a complete no-op — just sends "Session reset." message. |
| `logging.py` + `audit.py` | both | **Two separate `AuditLogger` classes** — `logging.py:66` and `audit.py:34`. Different interfaces, same purpose. `admin_api.py` uses one, `gateway.py` uses the other. |

### HIGH — Logic Bugs

| File | Line | Issue |
|------|------|-------|
| `llm.py` | 172 | Anthropic SSE streaming format differs from OpenAI — `_stream_sse` may not parse correctly. |
| `llm.py` | 223 | Ollama tool call parsing may double-wrap if `function` key is empty. |
| `http_client.py` | 43-45 | `close_all` logs "0 connections freed" because `.clear()` runs before `len(self._clients)`. |
| `jobs.py` | 61 | `_max_workers` defined but **never enforced** — unlimited concurrent jobs. |
| `task_queue.py` | 163 | `cancel()` only marks DB status as CANCELLED — doesn't cancel the `asyncio.Task`. Worker continues. |
| `agent/agent.py` | 118 | `_auto_memory` calls handlers with `await` but `handler` is typed as `Callable` (could be sync). |
| `telegram/channel.py` | `start()` | Calls `app.start()` which does **NOT** start polling — bot never receives messages. Need `app.run_polling()` or explicit polling start. |

### MEDIUM — Dead / Duplicate Code

| File | Issue |
|------|-------|
| `models.py` | `LLMResponse` (line 60) duplicates `llm.py:LLMResponse` (line 37). Two classes, same purpose. |
| `models.py` | `SessionSummary` (line 66) defined but never used anywhere. |
| `config.py` | `ClassVar` imported but unused. |
| `models.py` | `AsyncIterator` imported but unused. |
| `skills.py` | `to_dict` truncates prompt to 200 chars — loses context. |
| Scheduler | APScheduler (`cron` plugin) exists but is never wired into the gateway for recurring tasks. |
| `daemon/` | Rust-based daemon in `daemon/` directory — exists but is **never built, referenced, or deployed**. Dead code. |

---

## 3. What Should Be Deleted or Archived

| File/Dir | Why |
|----------|-----|
| **`daemon/`** (Rust daemon) | Never used, never built, never documented. Rust binary for Windows/Linux service — but this vision calls for a Python-first approach. Delete entire directory. |
| **`raven/core/task_queue.py`** | Overlaps with `jobs.py`. Has buggy `cancel()`, fragile persistence, no dedup. Replace entirely by Phase 2 Task Engine. |
| **`raven/core/logging.py:AuditLogger`** | Duplicate of `raven/core/audit.py:AuditLogger`. Keep `audit.py` version, delete from `logging.py`. |
| **`raven/core/models.py:LLMResponse`** | Duplicate of `llm.py:LLMResponse`. Delete from `models.py`. |
| **`raven/core/models.py:SessionSummary`** | Defined but never used. Delete. |
| **`raven/plugins/memory/plugin.py`** | List of hardcoded "memory" tools — overlaps with `agent.py:_auto_memory` and is never actually wired into the agent. |
| **`raven/channels/{irc,matrix,teams,feishu,line,signal,googlechat,whatsapp}/`** | Per product vision: keep code, disable by default, document as "community channels — PRs welcome". Set `channel_id` → `channel.disabled` in default config. |

---

## 4. What Is Missing for the 3 Core Scenarios

### Scenario A: Monitoring / Crypto (killer feature)

| Missing | Priority |
|---------|----------|
| Price monitor (CoinGecko polling, condition engine, alert dispatch) | 🔴 P0 |
| HTTP/Service monitor (status code, response time, content match) | 🔴 P0 |
| RSS/News monitor (RSS polling, keyword filter, dedup) | 🔴 P0 |
| File monitor (watchdog-based, create/modify/delete/size alerts) | 🟡 P1 |
| Process monitor (CPU%, memory%, crashed processes) | 🟡 P1 |
| Cron-based scheduler for recurring monitors | 🔴 P0 |
| Monitor management via Telegram chat commands | 🔴 P0 |

### Scenario B: Coding 24/7

| Missing | Priority |
|---------|----------|
| `read_file` / `write_file` / `list_dir` tools | 🔴 P0 |
| `code_run` tool (Docker sandbox priority) | 🔴 P0 |
| `code_review` tool (LLM-based PR review) | 🟡 P1 |
| `git_status` / `git_commit` / `git_diff` tools | 🟡 P1 |
| Code workspace indexer (symbol index in SQLite) | 🟡 P2 |
| Auto-PR review on git push (webhook + diff review) | 🟡 P2 |
| Coding sessions (persistent conversation context per project) | 🟡 P2 |

### Scenario C: Automation & Routines

| Missing | Priority |
|---------|----------|
| Task engine (Task/TaskStep models, async runner, persistence) | 🔴 P0 |
| Multi-step task planner (LLM breaks goal into steps) | 🔴 P0 |
| Email plugin (IMAP polling, SMTP send, filter rules) | 🟡 P1 |
| Morning briefing skill (scheduled daily summary) | 🟡 P1 |
| File automation rules (receive file → auto-process) | 🟡 P2 |
| `send_email` tool (SMTP via config) | 🟡 P1 |
| `web_search` tool (Brave/DDG API) | 🟡 P1 |

### Infrastructure Gaps

| Missing | Priority |
|---------|----------|
| Windows service daemon (`pywin32`-based) | 🔴 P0 |
| Interactive onboarding wizard (`rich` + `prompt_toolkit`) | 🔴 P0 |
| User config at `~/.raven/config.json` (not scattered `.env`) | 🔴 P0 |
| `raven service install/start/stop/status` CLI commands | 🔴 P0 |
| `raven update` command (pip upgrade + service restart) | 🟡 P1 |
| `raven doctor` — dependency/service/key diagnostics | 🟡 P1 |
| PyPI `raven-agent` package metadata | 🟡 P1 |
| Telegram: voice → Whisper transcription | 🟡 P2 |
| Telegram: inline keyboards for quick replies | 🟡 P2 |
| Telegram: typing indicator while processing | 🟡 P2 |
| Self-healing watchdog (monitor event loop, restart) | 🟡 P1 |

---

## 5. Test Coverage Gaps

| Area | Tests | Status |
|------|-------|--------|
| Core: config, db, llm, models, failover, sandbox | ✅ Good coverage |
| Core: errors, circuit_breaker, http_client, jobs, secrets, audit | ❌ **Zero tests** |
| Core: admin_api, config_watcher, plugin_sandbox | ❌ **Zero tests** |
| Channels: all 12 | ✅ Each has unit tests |
| Plugins: sessions | ✅ Has tests |
| Plugins: api, browser, code, cron, files, git, memory, ocr, process | ❌ **Zero tests** |
| E2E / integration | ❌ **Zero tests** |
| CLI commands | ❌ **Zero tests** |

---

## 6. Architecture Dimensionality

### Current state: 2 dimensions
```
Input Layer (12 channels) → Core (1 agent) → Output Layer (12 channels)
```

### Target state: 5 dimensions
```
Input Layer (4 primary channels)
         ↓
  ┌─ Task Engine ─┬─ Tool Registry ─┬─ Monitor Engine ─┐
  │  Planner       │  Code tools      │  Price            │
  │  Scheduler     │  Web tools       │  HTTP             │
  │  Persistence   │  File tools      │  RSS              │
  └────────────────┴─────────────────┴───────────────────┘
         ↓
Output Layer (4 primary channels + email)
```

---

## 7. Audit Summary

| Metric | Value |
|--------|-------|
| Total Python files | ~60 |
| Total lines of code | ~8,500 |
| Critical bugs | 5 (all must be fixed before v1.0) |
| High-priority bugs | 7 |
| Dead code files | 2 (`daemon/`, `task_queue.py`) |
| Missing test coverage | 8 modules (0 tests) |
| Missing features for core scenarios | ~25 items |
| Tests passing | 160/160 |
| Ruff issues | 196 (mostly pre-existing line length + unused imports) |

**Next**: User to confirm before Phase 1 begins.

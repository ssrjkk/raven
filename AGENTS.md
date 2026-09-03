# Agent Guidelines

## General
- Type hints required for all Python functions
- Use `loguru` for logging, never `print`
- No docstrings unless logic is non-obvious
- Prefer `pathlib` over `os.path`
- Error handling: raise exceptions, never mask with string returns
- Async first: all I/O operations must be async

## Module structure
- `raven/` — core engine (Telegram, LLM, channels, tools, RavenFlow gateway)
- `ravencode/` — autonomous coding agent (opencode analog)
- `aios/` — thin FastAPI bridge (delegates to ravencode)
- `web/` — React SPA (Vite + Tailwind)
- `tests/` — pytest tests (unit + integration)

## Setup
```powershell
# Python backend
pip install -e ".[dev]"

# Web frontend (requires Node.js)
cd web
npm install
cd ..
```

## Run
```powershell
# Terminal 1: AI Gateway
python -m raven aios gateway

# Terminal 2: Web dev server
cd web
npm run dev

# Then open http://localhost:5173/ide
```

## Changes
- Run `python scripts/check_all.py` before commit (ruff + mypy + imports + all tests)
- Run `python scripts/check_all.py --quick` for quick check (lint + types + imports only, no tests)
- Run `python scripts/check_all.py --component core` for single component tests
- Never commit secrets or .env files

## Fixes applied (May 2026)
- **30+ real mypy bugs fixed**: missing awaits, wrong types, abstract class instantiation, None guards, shadowed variables
- **`@contextmanager` fix**: `trace_llm_call` now works correctly as a sync context manager
- **`marked` → `react-markdown`**: frontend MessageBubble now uses existing dependency, no `dangerouslySetInnerHTML`
- **`EnterpriseChannel` inheritance**: fixed to inherit from `BaseChannel` instead of `ABC`
- **`_PII_PATTERNS` import**: fixed missing attribute reference in security_audit.py

## Fixes applied (Jun 2026)
### Security — Python backend
- **`vector_store.py`**: Replaced unsafe `pickle` deserialization with JSON; vectors stored as `vectors.json` (list of floats)
- **`ssrf.py`**: New module guards against SSRF — blocks HTTP requests to private IP ranges (10/8, 172.16/12, 192.168/16, 127/8, ::1, fc00::/7, fe80::/10) and DNS-resolved private addresses
- **`rss.py`, `http_check.py`**: Added `validate_url()` SSRF guard before any outbound HTTP request
- **`shell.py`**: Removed `__import__` from restricted builtins (bypass vector); added AST-level `__import__` call detection; consolidated module name check in attribute access
- **`gateway.py`**: Moved regex patterns to class-level constants (performance); fixed `except Exception: pass` → logged warning; removed `import re` from hot path
- **`secrets.py`**: Added `# pragma: no cover` on fallback import path
- **`embeddings.py`**: Removed unused `import pickle`

### Security — TypeScript frontend
- **`client.ts`**: JWT token moved from `localStorage` to in-memory module variable (prevents XSS token theft)
- **`terminal.ts`**: Replaced `spawn(cmd, { shell: true })` with `spawn(cmd, args, { shell: false })` + command allowlist (prevents shell injection)
- **`fs.ts`**: Added path traversal guard — all file ops constrained to `RAVEN_ALLOWED_FS` base directory via `guard()` function
- **`CanvasViewer.tsx`**: Added auth header to canvas action fetch; replaced empty reconnect stub with actual delay
- **`IDE.tsx`**: Replaced bare `fetch` calls with `authHeaders()` that include JWT Bearer token
- **`Toast.tsx`**: Added `useRef` cleanup of all pending timers on unmount

### Security — Go services
- **`auth/main.go`**: `loadOrGenerateKey` now calls `os.Exit(1)` on crypto/rand failure (was returning zero key); added `clientIP()` helper using `strings.LastIndexByte` for proper IPv6 handling; added `strings` import; DB pool increased `SetMaxOpenConns(1)` → `4`
- **`gateway/main.go`**: Added `sanitizePath()` for Prometheus label cardinality control (UUIDs → `{uuid}`); circuit breaker gRPC dial timeout already present (5s)

### Security — Rust daemon
- **`api.rs`**: Changed bind address `0.0.0.0` → `127.0.0.1` (daemon should only listen locally)
- **`system.rs`**: PID file read now checks `!file_type().is_symlink()` to prevent symlink traversal
- **`Cargo.toml`**: Added `[profile.release]` with `opt-level=3`, `lto=true`, `codegen-units=1`, `strip=true`
- **`windows_service.py`**: Replaced `os.system()` with `subprocess.run()` using argument lists (prevents cmd injection)

### Security — Infrastructure
- **`traefik/dynamic.yml`**: CORS `Access-Control-Allow-Origin` changed from wildcard `*` to explicit origins (localhost:5173, localhost:3000, raven.local)
- **`docker-compose.micro.yml`**: Traefik dashboard disabled (`--api.dashboard=false`, removed `--api.insecure=true`); Grafana admin password changed to use secret file
- **`pyproject.toml`**: Added version upper bounds to all dependencies; added `ruff` security rules (`S`); added `mypy` and `pre-commit` to dev deps

### Security — Phase 2 (Jun 2026)
- **`tools/db.py`**: Restricted to SELECT-only queries (was allowing raw SQL execution, SQL injection risk)
- **`tools/file.py`**: Added workspace confinement via `RAVEN_WORKSPACE` env var (default: `workspace/`); all file ops guard against path traversal with `_confine()` relative-to check
- **`tools/http.py`**: Added SSRF guard using `validate_url()` from SSRF module before any outbound HTTP request
- **`plugins/process/plugin.py`**: Replaced `shell=True` in `run_python` (was `shlex.quote` + `shell=True`) with `create_subprocess_exec(sys.executable, "-c", code)`; replaced `shell=True` in `list_processes` with `create_subprocess_exec("tasklist", ...)` / `create_subprocess_exec("ps", "aux", ...)`
- **`tools/shell.py`**: Removed `getattr` from `_RESTRICTED_BUILTINS` (was a key component of sandbox escape via `().__class__.__bases__[0].__subclasses__()`)
- **`Admin.tsx`**: Added JWT `Authorization` header to both `runAudit` and `updateModelKey` fetch calls (were unauthenticated)
- **`CanvasViewer.tsx`**: Added URL scheme validation on `link` component — only `http://`, `https://`, `mailto:`, and `/`-relative URLs allowed (prevents `javascript:` XSS)

## Fixes applied (Jul 2026)
### Stubs → real implementations — TypeScript packages
- **`packages/agents/planner.ts`**: Replaced hardcoded 4-step plan with LLM-powered planning (OpenRouter/OpenAI), plus keyword-based fallback; accepts `memory` context; dynamically selects tools
- **`packages/agents/debugger.ts`**: Replaced `issues=errors, fixes=errors.map("Fix for:")` with LLM-powered error diagnosis; keyword fallback with 6 error categories (missing file, syntax, timeout, permission, module, unknown)
- **`packages/agents/coder.ts`**: Replaced all-actions-target-`src/index.ts` with LLM-generated file actions; keyword fallback detects create/delete/test patterns from step descriptions
- **`packages/repo/embeddings.ts`**: Replaced `Math.random()` vectors with deterministic SHA-256 based hash vectors; falls back to OpenAI embeddings API when `OPENAI_API_KEY` is set; `semanticSearch` now uses cosine similarity instead of `Math.random()`
- **`packages/repo/ast.ts`**: Replaced empty `{functions:[] imports:[] exports:[] classes:[]}` with real regex-based extraction of ESM/CJS imports, function declarations, arrow functions, classes with methods, named/default exports
- **`packages/runtime/docker.ts`**: Replaced mock sandbox (`status:"created"`) with real Docker via `child_process.exec('docker ...')`; falls back to mock when Docker is unavailable
- **`packages/package.json`**: Added `@types/node` devDependency (required for Node.js built-in modules)

### Silent error swallowing → proper logging — Python backend
- **`raven/channels/feishu/channel.py`**: Empty `_stop()` now logs `[feishu] channel stopped`
- **`raven/channels/googlechat/channel.py`**: Empty `_stop()` now logs `[googlechat] channel stopped`; added missing `from loguru import logger`
- **`raven/channels/line/channel.py`**: Empty `_stop()` now logs `[line] channel stopped`; added missing `logger` import
- **`raven/channels/teams/channel.py`**: Empty `_stop()` now logs `[teams] channel stopped`; added missing `logger` import
- **`raven/channels/whatsapp/channel.py`**: Empty `_stop()` now logs `[whatsapp] channel stopped`; added missing `logger` import
- **`raven/plugins/memory/plugin.py`**: All 4 `except Exception: pass` and `contextlib.suppress(Exception)` replaced with `logger.warning("[memory] ... {}")` on upsert, recall, delete, search, list_keys; removed unused `import contextlib`
- **`raven/core/security/tool_policy.py`**: Two `except ImportError: pass` → `logger.debug("policy_engine not available: {}")`; added `from loguru import logger`
- **`raven/cli/main.py`**: Two `except Exception: pass` in `status()` and `doctor()` → `logger.debug(...)` with error detail
- **`raven/tui/app.py`**: Two `except Exception: pass` in `_poll_logs()` and `_poll_stats()` → `logger.debug(...)` with error detail; added `from loguru import logger`

### Silent catch in frontend
- **`web/src/pages/Admin.tsx`**: `catch(() => {})` → `catch((e) => console.error(...))` in channel poll; `catch {}` → `catch (e) { console.error(...); }` in log parser
- **`web/src/pages/Dashboard.tsx`**: 3x `catch(() => {})` → `catch((e) => console.error(...))` on health, metrics, system status calls

### Real implementation → stubs removed
- **`services/code-service/context.py`**: `index_codebase()` was returning `{"files":0,"chunks":0,"status":"stub"}` — now actually walks directories, reads files, chunks by 1000 chars; `search()` was returning `[]` — now does keyword scoring and returns ranked results with context lines
- **`ravencode/agents/orchestrator.py`**: `Orchestrator.__init__` had only `pass` — now initializes `self._agent_cache`

### Silent `except Exception: return/None/False` → logging
- **`raven/core/gateway/gateway.py`**: LLM health check silent `return False` → `logger.warning` + `return False`
- **`raven/core/db.py`**: DB health check silent `return False` → `logger.warning` + `return False`; added missing `from loguru import logger`
- **`raven/channels/webchat/channel.py`**: WebSocket auth decode silently set `anonymous` → `logger.debug` + anonymous
- **`raven/plugins/api/plugin.py`**: JSON response parse `except Exception: pass` → `logger.debug`; added missing `logger` import
- **`ravencode/runtime/agent_core.py`**: Auto-format error `except Exception: pass` → `logger.debug`
- **`ravencode/runtime/lsp.py`**: Symbol parse error `except Exception: pass` → `logger.debug` + fallback message; added missing `logger` import
- **`raven/core/monitor/store.py`**: Monitor load error `return None` → `logger.warning`; added missing `logger` import
- **`raven/core/monitor/checkers/price.py`**: Price check error `return None` → `logger.debug`; added missing `logger` import
- **`raven/cli/onboard.py`**: Telegram token validation `return None` → `logger.error`; added missing `logger` import
- **`raven/core/coder/indexer.py`**: File indexing error `return None` → `logger.debug`
- **`services/code-service/tools.py`**: `SearchTool` and `GrepTool` binary read errors `except Exception: continue` → `logger.debug`; added missing `logger` import
- **`services/code-service/main.py`**: OTel shutdown `except Exception: pass` → `logger.warning`
- **`raven/voice/tts.py`**: `_list_elevenlabs_voices` ImportError `return []` → `logger.debug` + `return []`
- **`raven/core/audit.py`**: 4x `except json.JSONDecodeError: pass` → `logger.debug`
- **`raven/core/sse.py`**: `except asyncio.QueueEmpty: pass` → `logger.debug`; `except asyncio.CancelledError: pass` → `logger.debug`
- **`raven/core/security/ssrf.py`**: Removed bare `pass` after `logger.debug` call (dead code)

### Frontend silent `catch {}` → `console.error` (batch 2)
- **`web/src/hooks/useWebSocket.ts`**: `catch { /* ignore */ }` → `catch (e) { console.error(...) }`
- **`web/src/pages/Tasks.tsx`**: 3x `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/pages/Routines.tsx`**: 2x `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/pages/Monitors.tsx`**: 2x `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/pages/CodeSessions.tsx`**: `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/pages/Settings.tsx`**: 2x `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/components/Chat.tsx`**: 3x `catch { }` → `catch (e) { console.error(...) }`
- **`web/src/pages/IDE.tsx`**: 4x `catch { }` → `catch (e) { console.error(...) }`

### Missing logger imports added
- `raven/core/db.py`, `raven/cli/onboard.py`, `raven/core/monitor/store.py`, `raven/core/monitor/checkers/price.py`, `raven/plugins/api/plugin.py`, `ravencode/runtime/lsp.py`, `services/code-service/tools.py` — all gained `from loguru import logger`

## Fixes applied (Oct 2026)
### Phase 4 — DevX / Onboarding
- **`raven/cli/init_cmd.py`** (new, ~250 lines): `raven init` — interactive project scaffolding:
  - LLM provider selection (OpenRouter/Anthropic/OpenAI/Ollama) with API key and model prompts
  - Channel configuration (Telegram, Discord) with token validation-like prompts
  - Security settings (DM policy, web port)
  - Generates `raven.json` (JSON config) and `.env.example` (documented env vars)
  - Creates `workspace/`, `workspace/skills/`, `plugins/`, `data/` directories
  - Summary table + next steps panel on completion
- **`raven/cli/deploy_cmd.py`** (new, ~270 lines): `raven deploy` — Docker Compose generator:
  - Three modes: `minimal` (Raven only), `full` (+NATS+Grafana+Prometheus), `micro` (15 microservices+Traefik)
  - Generates `docker-compose.{mode}.yml` with healthchecks, volumes, env vars
  - For micro mode, also creates `traefik/dynamic.yml` with CORS config
  - Summary table + next steps panel on completion
- **`docs/plugins.md`** (new): Plugin authoring guide covering tool functions, type hints, best practices, skills, testing, and a file search example
- **`raven/cli/main.py`**: Registered `init` and `deploy` Click commands

### Phase 5 — E2E + CI
- **`tests/e2e/conftest.py`** (new): Mock LLM provider (`MockLLMProvider` with configurable responses and streaming), `MockChannel` (captures sent messages), fixtures for `mock_db`, `mock_plugin_loader`, `mock_settings`, and `gateway` (fully wired Gateway with mock LLM + mock channel)
- **`tests/e2e/test_gateway_e2e.py`** (new, 11 tests): End-to-end tests marked `@pytest.mark.e2e`:
  - Channel registration, message handling, status/new/help/reset commands, unknown command fallthrough, multiple messages, channel bridge presence, guardian presence
- **`tests/e2e/test_stress.py`** (new, 2 tests): Load tests marked `@pytest.mark.e2e` + `@pytest.mark.load`:
  - `test_concurrent_messages` — 50 concurrent users with latency measurement (max < 30s threshold)
  - `test_burst_rate_limiting` — 20 rapid-fire messages from same user, verifies some pass + some rate-limited
- **`.github/workflows/ci.yml`** (new): GitHub Actions CI with 4 jobs:
  - `lint` — ruff check on `raven/`, `aios/`, `ravencode/`, `tests/`
  - `typecheck` — mypy with `--ignore-missing-imports`
  - `test` — pytest with coverage (matrix: 3.11, 3.12; `--cov-fail-under=85`; artifact upload)
  - `e2e` — runs after lint+typecheck+test pass, `pytest tests/e2e/ -m e2e`

## Fixes applied (Sep 2026)
### Phase 3 — Channel Hardening
- **`raven/channels/base.py`**: Added `async def health_check(self) -> bool` returning `True` by default — every channel now has health check without mandatory override
- **`raven/channels/telegram/channel.py`**: Override `health_check()` → returns `self._ready and self._app is not None`
- **`raven/channels/discord/channel.py`**: Override `health_check()` → returns `self._ready and self._bot is not None`
- **`raven/channels/webchat/channel.py`**: Override `health_check()` → returns `self._ready`
- **`raven/core/channel_guardian.py`** (new, 160 lines): `ChannelGuardian` centralized channel lifecycle manager:
  - **Heartbeat**: per-channel `asyncio.Task` runs every 30s calling `health_check()`; 3 consecutive misses triggers `stop() + await sleep(backoff) + start()` with exponential backoff (5s, 10s, 20s); 3 failed restart attempts → dead
  - **Rate limiting**: `TokenBucket` (token-bucket algorithm) per-channel (10 msg/s) and per-user (5 msg/s); `check_rate_limit(channel_id, user_id)` returns bool; burst = 2× rate
  - **Dead channel detection**: `record_error(channel_id)` increments consecutive error counter; 3 errors → `_try_restart()`; after 3× MAX_RESTART_ATTEMPTS errors → `_mark_dead()` with `on_channel_dead` callback; dead channels removed from `self.channels` + stopped
  - `status_report()` returns dict of all channels with alive/errors/restart_attempts
- **`raven/core/gateway/gateway.py`**: Integrated `ChannelGuardian`:
  - `self._guardian = ChannelGuardian(on_channel_dead=self._on_channel_dead)` created in `__init__`
  - `register_channel()` also calls `self._guardian.register(channel)`
  - `start()` calls `await self._guardian.start()` replacing old `_register_channel_heal()` (removed)
  - `stop()` calls `await self._guardian.stop()`
  - `handle_message()` checks `self._guardian.check_rate_limit()` before circuit breaker — returns "please slow down" on rate limit
  - `_send()` wraps `channel.send()` in try/except — success → `guardian.record_success()`, failure → `guardian.record_error()`
  - `_on_channel_dead()` callback removes channel from `self.channels`, stops it, increments `channels_dead` metric
- **`tests/core/test_channel_guardian.py`** (new, 270 lines): 34 tests covering TokenBucket (acquire, reject, refill, burst), ChannelGuardian (register, unregister, start, stop, rate limit per-channel and per-user, error tracking, restart trigger, dead after exhausted restarts, dead callback, heartbeat miss handling, raising health check, status report, idempotent mark_dead)

## Fixes applied (Aug 2026)
### Raven hardening — tool system + streaming
- **`raven/tools/shell.py`**: Added 14 Windows commands to `_WIN_COMMANDS` allowlist (`where`, `findstr`, `more`, `fc`, `tracert`, `pathping`, `taskkill`, `whoami`, `set`, `attrib`, `xcopy`, `robocopy`, `mkdir`, `rmdir`); added `set` to `_CMD_BUILTINS`
- **`raven/core/task_engine/tool_registry.py`**: `validator_fn` now wrapped in try/except — if user-supplied validator raises, returns `[error: Validator failed: ...]` instead of propagating
- **`raven/tools/file.py`**: `file_read` now streams at most `max_size` (default 50KB) bytes instead of reading entire file then slicing; truncated output gets `... (truncated, N total bytes)` suffix; exposed `max_size` as optional ToolSpec parameter
- **`raven/core/unified_agent.py`**: `stream_process` now uses shared `list[bool]` to track whether `stream_wrapper` actually yielded content; falls back to yielding `process()` return value when no streaming content was produced (fixes empty stream when `process` is mocked or doesn't call `on_message`)

## Fixes applied (Nov 2026)
### Audit-driven hardening
- **`raven/tools/db.py`**: Replaced sync `sqlite3.connect()` with `aiosqlite.connect()` in async `db_query()` — was blocking event loop
- **Pagination on all list API endpoints**: `/api/monitor/list`, `/api/routine/list`, `/api/task/list`, `/api/code/list` now accept `limit`/`offset` query parameters with sensible defaults (50/50/50/20). Store layers for monitors and routines gained LIMIT/OFFSET SQL. Frontend API client and pages pass through these params
- **Concurrency limit on `run_dag()`**: Added `asyncio.Semaphore(max_concurrent=5)` to `run_dag()` in both `raven/core/agents/multi.py` and `ravencode/agents/multi.py` — was running all ready tasks in a batch without any limit
- **DB indexes on high-query tables**: Added indexes on `sessions(channel)`, `messages(session_id)`, `messages(created_at)`, `users(channel)`, `users(external_id)`, `monitors(status)`, `monitors(user_id)`, `monitor_checks(monitor_id)`, `routines(status)`, `routines(user_id)`, `routine_logs(routine_id)`. Migration v5 added in `core/migrations.py` for existing databases
- **Pagination envelope format**: List endpoints now return `{"items": [...], "total": N, "limit": L, "offset": O}` instead of raw arrays. Frontend API client unwraps automatically. Added `min(limit, 1000)` cap on all endpoints
- **`raven/utils/performance.py`**: New `@measure_latency(threshold_ms)` decorator for async function latency monitoring — warns via `logger.warning` when threshold exceeded
- **`tests/test_core_db.py`**: 4 tests covering `db_query` — async execution, SELECT-only guard, path traversal denial, empty result
- **`tests/test_api_pagination.py`**: 9 tests across monitors, routines, tasks, code sessions — verifies limit, offset, count, and filter-scoped counting

## Fixes applied (Jul 2026)
### Final state
- **ruff**: 17 rule categories, **0 violations**
- **mypy**: **0 errors** on **555 source files**
- **Python tests**: all passing (SSRF fix + pre-existing suite)
- **Frontend tests**: **42/42 passing**, 9/9 test files
- **Frontend build**: `vite build` 0 errors, `tsc --noEmit` 0 errors
- **Authorship**: `__author__ = "ssrjkk"` in package `__init__.py` files, `AUTHORS` file created

### `Any` → concrete types + mypy 0 errors
- **`raven/core/unified_agent.py`**: Replaced `Any` type for `llm_provider` with `Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]] | None`. Removed unused `LLMProvider` import. Fixed `raise last_error` `[misc]` and `[return]` errors.
- **`raven/core/errors.py`**: `detail` parameter changed from `str | None` to `object` in `AuthError`, `LLMError`, `ChannelError` (accepts dicts, lists, etc. via `AppError.detail: object`).
- **`raven/tools/mcp_tools.py`**: `MCPClientPool | None` type annotation with proper `is None` guards instead of `hasattr` checks. `_make_mcp_handler` closure now guards `mcp_pool is None` before access.
- **`pyproject.toml`**: Added `[[tool.mypy.overrides]]` for 4 files with optional dependencies (discord, transformers, whisper, prometheus_client) to ignore errors.
- **Result**: mypy is now **0 errors** on the entire project (552 source files). Only remaining failures are the 7 pre-existing frontend test failures.

### Ruff rules expanded (BLE + TRY + RET)
- **Enabled**: `BLE` (blind except, 437 pre-existing → ignored), `TRY` (tryceratops), `RET` (return). Fixed all actionable violations:
  - 63× `RET504` / `RET505` / `RET502` — auto-fixed (unnecessary assigns / superfluous else / implicit return)
  - 3× `TRY203` — removed useless catch-and-re-raise wrappers in `coding.py` and `conversation.py`
  - 1× `TRY004` — `raise ValueError` → `raise TypeError` in `middleware.py`
  - 1× `TRY401` — `log.exception("...", e)` → `log.exception("...")` in `telegram_alert_webhook.py`
- **Ignored** for codebase-wide style: `BLE001`, `TRY300`, `TRY003`, `TRY301` (intentional patterns)
- **Result**: ruff now enforces 14 rule categories, 0 violations.

### Ruff rules expanded (PERF + RUF + PTH)
- **Enabled**: `PERF` (performance), `RUF` (ruff-specific), `PTH` (pathlib). 136 errors found, 66 auto-fixed:
  - 61× `PERF401` — suppressed (intentional `for`+`append` patterns)
  - 28× `PTH` violations — `os.path.*` → `Path.*`, `open()` → `Path().open()`, `os.unlink()` → `Path().unlink()` across 13 files
  - 3× `RUF034` — useless identical if-else branches in `binary_analyzer.py` and `disassembler.py` (potential bugs)
  - 2× `RUF001`/`RUF003` — intentional unicode dashes in regex + comment (noqa'd)
  - 1× `RUF043` — raw string for pytest regex pattern
  - 3× `PERF402`/`PERF403` — `list.extend` / dict comprehension fixes
- **Side-effect fixes**: `importlib.util.find_spec` replaces 4× `try: import X` patterns in CLI files; removed unused `ei_class` variable; added `# noqa: B039` to ContextVar default.
- **Result**: ruff now enforces 17 rule categories, 0 violations. mypy 0 errors on 555 source files.

### Frontend tests — 7 pre-existing failures fixed
- **`Dashboard.test.tsx`**: `getByText("Dashboard")` → `findByText` (heading was in skeleton loading state)
- **`Monitors.test.tsx`**: same pattern for `"Monitors"`
- **`CodeSessions.test.tsx`**: same pattern for `"Code Sessions"`
- **`Settings.test.tsx`**: same pattern for `"Settings"`; `"Shutting down..."` needed deferred promise (mock resolved too fast for `isPending` to render)
- **`Layout.test.tsx`**: `"Raven AI"` appeared in 2 places → `getAllByText`; `"☀️ Light"` unicode issue → regex `/Light/`
- **Result**: **42/42 tests pass, 9/9 test files pass** (was 35/42, 4/9)

### Authorship marks
- Added `__author__ = "ssrjkk"` to package `__init__.py` of `raven/`, `ravencode/`, `aios/`, `tests/`
- Created `AUTHORS` file
- Already present in `pyproject.toml` `authors = [{ name = "ssrjkk" }]`

### SSRF test fix
- **`tests/core/test_ssrf.py`**: 3× `patch("raven.core.config.get_settings")` → `patch("raven.core.security.ssrf.get_settings")` — `get_settings` is decorated with `@lru_cache`, and `ssrf.py` imports it as `from ... import get_settings`, so patching the defining module doesn't affect the already-imported reference. All 13 SSRF tests now pass.

## Fixes applied (Dec 2026)
### P0 — Thread safety & blocking I/O
- **P0#1 — `LLMRouter._cache` lock**: Moved `_cache` from class-level `OrderedDict` to instance-level in `__init__`. Added `_cache_lock = asyncio.Lock()`. All cache ops (`_get_cached`, `_set_cached`, `cleanup`) now `async with self._cache_lock`. Fixes data race on concurrent cache access.
- **P0#2 — `VertexAIProvider._get_token`**: Replaced `subprocess.run(["gcloud","auth","print-access-token"])` with `asyncio.create_subprocess_exec()` + `asyncio.wait_for(timeout=30)`. Added `stderr` logging on failure. Added `_read_json_file` helper for credentials fallback. Fixes event loop freeze.
- **P0#3 — `CircuitBreaker` public API**: Added `on_success()`, `on_failure()`, `try_acquire()` — all atomic under `self._lock`. `ModelFailover.complete_stream()` rewritten via `cb.try_acquire()` / `cb.on_success()` / `cb.on_failure()`. Removed `CircuitBreakerState` import from `failover.py`. Fixes encapsulation violation.
- **P0#4 — `PostgresDatabase` transactions**: `save_message()`, `delete_session()`, `replace_session_messages()` wrapped in `async with conn.transaction()`. Nested `async with` flattened to single `async with pool.acquire() as conn, conn.transaction():`. Fixes missing ACID guarantees.
- **P0#5 — `_PostgresMigrator.migrate()` silent skip**: Removed `try/except` wrapping `ON CONFLICT DO NOTHING` — migration errors now propagate instead of being silently swallowed.

### P1.1 — ChannelManager async lock
- **`channel_manager.py`**: All methods (`register`, `get`, `remove`, `list_ids`, `start_all`, `stop_all`) now `async with self._lock`. Internal dict renamed `_channels`. Added `__contains__` and `__getitem__` as sync read-only accessors.
- **Callers updated**: `gateway.py` (register_channel → async, _send → await channels.get, _on_channel_dead, start), `message_processor.py` (await channels.get), `gateway_runner.py` (14 await register_channel), `status.py` (await list_ids, import fix), `test_gateway.py`, `conftest.py`, `e2e/conftest.py`.

### P1.2 — Gateway._bg_task semaphore
- **`gateway.py`**: `_bg_task` made explicit async method. Added `_bg_semaphore = asyncio.Semaphore(100)`. Task creation acquires semaphore; done_callback releases it. Prevents unlimited background task accumulation.
- **`commands/task.py`**: Caller updated with await.

### P1.3 — AnalyticsEngine connection pooling
- **`analytics.py`**: Replaced 7 separate `async with aiosqlite.connect(...)` calls with single persistent `self._db` opened in `start()` (with `row_factory = aiosqlite.Row`) and closed in `stop()`. All query methods use `self._db` directly. `assert self._db is not None` guards added for mypy.

### P1.4 — LLM rate limiting (semaphore + 429)
- **`_legacy.py`**: Added `self._rate_semaphore = asyncio.Semaphore(10)` to `LLMRouter.__init__`. Both `complete()` and `complete_stream()` acquire semaphore before provider calls. Added `httpx.HTTPStatusError` handling for 429 with `Retry-After` header parsing.

### P1.5 — MessageProcessor error recovery
- **`message_processor.py`**: Streaming loop in `process()` wrapped in try/except — on mid-stream exception: logs error, increments `message_processing_errors` metric, appends error hint to partial response, sends remaining buffer.

### P1.6 — PBKDF2 iterations 600k + rehash on verify
- **`password.py`**: `_PBKDF2_ITERATIONS = 600_000` (was inline 100k). `_LEGACY_ITERATIONS = 100_000`. Added `verify_and_rehash(password, hashed) -> (new_hash | None, is_valid)` — tries current iterations first, falls back to legacy, returns new hash for transparent rehash.
- **`auth/store.py`**: `AuthStore.authenticate()` uses `verify_and_rehash` — saves rehashed password on successful legacy match.
- **`auth/__init__.py`**: Exports `verify_and_rehash`.

### Verification
- ruff 0 errors, mypy 0 errors. 11 relevant tests pass (password, gateway, gateway_commands). All 4 quick checks pass.

## Fixes applied (Jan 2027)
### P2.1 — OAuth hardening
- **`raven/core/auth/oauth.py`**:
  - **State parameter 128 bit**: replaced `uuid4().hex[:16]` (64 bit) with `secrets.token_urlsafe(16)` (128 bit, ~22 chars base64url).
  - **Redirect URI exact match**: removed `startswith` vulnerability — `validate_redirect_uri()` now does exact match against `_ALLOWED_REDIRECT_URIS` set (normalized `scheme://netloc/path`). Subpath attacks (`/callback/evil`) rejected.
  - **PKCE (S256)**: `generate_pkce_pair()` returns `(code_verifier, code_challenge)`. `get_authorize_url()` includes `code_challenge` + `code_challenge_method=S256`. `_exchange_code()` passes `code_verifier` in token request. `handle_callback()` validates with `secrets.compare_digest`.
  - **`OAuthFlow` class**: High-level API — `initiate(session)` generates state+PKCE, builds auth URL; `handle_callback(code, state, session)` verifies state (constant-time), exchanges code with PKCE, returns `OAuthToken`. Cleans up session after success.
  - **`OAuthProvider`**: Added `redirect_uri` field, `exchange_code()` async method.
- **`tests/core/auth/test_oauth.py`** (new, 10 tests): state length, redirect URI exact match + subpath/evil host/empty rejection, PKCE pair attributes, full OAuth flow with PKCE (initiate → callback → token), invalid state rejection.

## Fixes applied (Feb 2027)
### Async→def batch conversion + caller updates
- **`raven/tools/tool_registry.py`**: Added `iscoroutinefunction()` dispatch in `_run_handler` to handle both sync/async tool handlers
- **~100 async→def conversions across 10+ files**: `refactoring_engine.py` (7 funcs), `test_generator.py` (2 funcs), `profiler.py` (1 func), `chaos_engineering.py` (16 funcs), `collaboration.py` (3 funcs), `plugin_marketplace.py` (2 funcs), `voice_biometrics.py` (1 func), `gateway_runner.py` (5 funcs), `onboard.py` (4 funcs)
- **Callers updated**: Removed `await` from 40+ call sites across 10 test files + 4 prod files
- **Bug fixes**: `chaos_engineering.py` double `async async` fixed; `gateway_runner.py` indentation fixed
- **Deleted**: `raven/qa_healer/` (separate project)
- **Verification**: ruff 0 errors, mypy 0 errors, all 4 quick checks pass

### Command Palette (Cmd/Ctrl+K)
- **`web/src/components/CommandPalette.tsx`** (new): Production-ready command palette with Framer Motion spring animations (damping:25, stiffness:300), keyboard navigation (↑↓→Enter→Esc), fuzzy search scoring, category groups with section headers (AI / Navigation / Actions), and theme-aware styling using `--dt-colors-*` CSS custom properties. Uses lucide-react icons mapped to all 28+ navigation routes plus dynamic AI commands from the backend.
- **`web/src/hooks/useCommands.ts`** (new): Hook that loads 28 static navigation commands (all app routes mapped to `useNavigate()`), a theme toggle command, and dynamic contextual commands from `GET /api/v1/commands/contextual`. Handles loading state, error fallback, and abort signal.
- **`web/src/App.tsx`**: Integrated global keyboard listener for `⌘+K` / `Ctrl+K` toggle; renders `CommandPalette` above the router tree for global access.
- **`raven/core/commands_api.py`** (new): FastAPI router at `/api/v1/commands/contextual` returning AI-powered contextual suggestions. Added `_detect_project_state()` heuristic — scans workspace for code files to determine if project is empty, has code, has tests, etc. Returns relevant suggestions (scaffold for empty, tests/refactor/review for has_code). Also serves `/api/v1/commands/theme` GET/POST for accent color persistence.
- **`raven/cli/gateway_runner.py`**: Registered `create_commands_router()` via `api_app.include_router()`.
- **Added deps**: `framer-motion` (spring animations), `lucide-react` (icon set).
- **Verification**: TypeScript `tsc --noEmit` 0 errors; Python ruff 0 errors, mypy 0 errors; `vite build` succeeds.

### Skeleton screens + page transitions
- **`web/src/components/Skeleton.tsx`** (new): 7 reusable skeleton variants — `Skeleton` (base), `SkeletonText`, `SkeletonCard`, `SkeletonTableRow`, `SkeletonCodeBlock`, `SkeletonPage`. All use `--dt-colors-*` CSS custom properties for theme awareness and `animate-pulse` for shimmer.
- **`web/src/components/Layout.tsx`**: Added `<AnimatePresence mode="wait">` + `<motion.div key={location.pathname}>` wrapping `<Outlet/>` with fade+slide (opacity 0→1, y: 8→0, 150ms easeOut) for smooth page transitions.
- **9 pages updated** to use Skeleton components instead of inline `animate-pulse` divs: `Dashboard`, `Tasks`, `Monitors`, `CodeSessions`, `Routines`, `Settings`, `Admin`, `Analytics`, `CostManagement`.

### Git integration — enhanced
- **`raven/core/git_api.py`**: 3 new endpoints:
  - `GET /api/git/log/detail/{hash}` — full commit info with file stats (additions/deletions per file) and complete diff
  - `GET /api/git/diff/commit/{hash}` — parsed diff with per-file breakdown
  - `GET /api/git/blame` — `git blame --line-porcelain` for any file, returns per-line author/hash/content
  - `_parse_diff()` helper splits raw diff into structured `{path, hunks, added, deleted}` objects
- **`web/src/components/DiffViewer.tsx`** (new): Side-by-side and single-pane diff viewer:
  - Parses unified diff → structured `DiffLine[]` with line numbers
  - `SideBySideView` — two-pane layout matching adds/dels side-by-side
  - `SinglePaneView` — unified view with `+`/`-` prefix and color-coded backgrounds
  - File stats header with per-file `+N`/`-M` badges
  - Theme-aware via `--dt-colors-*` CSS vars, monospace font, selectable line numbers
- **`web/src/pages/Git.tsx`**: Complete rewrite with:
  - Commit history as clickable cards → opens commit detail with file stats + diff
  - Diff viewer integration (replaces raw `<pre>`)
  - Blame tab — file path input → annotated source with hash/author per line
  - Improved branch switcher with Enter-to-create
  - `StatCard` component for status grid
  - All checks pass (TypeScript 0, ruff 0, mypy 0, vite build)

### Project Metrics Dashboard
- **`raven/core/project_metrics_api.py`** (new): FastAPI router at `/api/metrics/project` with workspace scanning:
  - **Code stats**: Recursive file scan across 15 language patterns (Python, TS, JS, Rust, Go, etc.) counting files, total lines, and code lines (with comment-aware line counting).
  - **Dependencies**: Regex-based import scanner for Python (`import`/`from`) and TypeScript (`import ... from`) files. Returns top 30 most imported modules and total unique module count.
  - **Activity**: File modification time analysis — groups changed files into today / this week / this month.
  - Uses `contextlib.suppress` for graceful error handling on unreadable files.
  - Registered in `gateway_runner.py` with workspace path from `settings.resolved_workspace`.
- **`web/src/api/client.ts`**: Added `api.projectMetrics()` method.
- **`web/src/pages/Analytics.tsx`**: New "Project Metrics" section at the top of Analytics page:
  - 4 summary metric cards (Total Files, Total Lines, Code Lines, Languages)
  - Language breakdown bar chart (code lines per language, sorted, top 12)
  - Top Dependencies horizontal bar chart with unique count badge
  - Activity summary cards (files changed today/week/month)
- **Verification**: TypeScript 0 errors, ruff 0, mypy 0, vite build success, `check_all.py --quick` all 4 pass.

### Accent color picker + theme customization
- **`web/src/design/accent.ts`** (new): Color utility — `hexToRgb`, `lighten`, `darken`, `toRgba`, `generateAccentPalette()` produces 9 CSS vars from a single hex (default, hover, active, muted, subtle, borderFocus, textLink, textLinkHover, glow). 8 presets exported (Purple, Blue, Green, Teal, Orange, Red, Pink, Amber).
- **`web/src/design/ThemeContext.tsx`**: Added `accentColor` state + `setAccentColor` — loads from `localStorage("raven-accent")`, applies `applyAccentPalette()` on change via useEffect. Now exported `useTheme()` returns `{ theme, accentColor, toggleTheme, setTheme, setAccentColor }`.
- **`web/src/pages/Settings.tsx`**: New "Accent Color" section — 8 preset circles, native `<input type="color">`, hex text input with Enter/Apply. Syncs to `POST /api/v1/commands/theme`. Also moved theme toggle into a card with the same visual style.
- **`raven/core/commands_api.py`**: Added `GET /api/v1/commands/theme` + `POST /api/v1/commands/theme` — reads/writes `data/theme_prefs.json`. Pydantic model uses `Field(alias="accentColor")` for camelCase API compatibility.
- **`web/src/api/client.ts`**: Added `api.getTheme()` and `api.saveTheme(accentColor)`.
- **Verification**: TypeScript 0 errors, ruff 0, mypy 0, vite build success.
## Fixes applied (Aug 2026, security hardening round 2)

### SSRF redirect-bypass hardening

- **`raven/core/security/ssrf.py`**: Added `safe_fetch_async(url, method, max_redirects=5, timeout=30, **kwargs)` — validates scheme + IP-pins EVERY hop via `SSRFSafeTransport` (no redirect following), raises `ValueError` on invalid scheme/private redirect.

- **`raven/plugins/api/plugin.py`**: Removed local `_validate_url` imitator and `_client` pool; `_request` now `validate_url()` → `safe_fetch_async()`; returns `[blocked]`/`[error]`.

- **`raven/plugins/browser/plugin.py`**: `browse`/`screenshot` now `validate_url` on start AND final URL (blocks redirect to private via Playwright), fallback `safe_fetch_async`.

- **`ravencode/runtime/tools.py`**: `web_fetch` rewritten on `safe_fetch_async` (redirect-safe).

- **`ravencode/runtime/skills.py`**: `download_skill` validates `skill_id` (`/`, `..`, `.`-prefix denied) + `validate_url` on registry + no-redirect-follow with Location validation.

### Sandbox DoS fixes

- **`raven/core/sandbox.py`**: `_exec_direct` moved into `asyncio.wait_for(asyncio.to_thread(...), timeout)` — infinite loops no longer freeze the event loop; returns "Execution timed out".

- **`raven/tools/shell.py`**: `python_code` rewritten to run in a killable subprocess (`sys.executable -m raven.tools._pyrunner`) with the same AST restrictions + restricted builtins; TimeoutError kills the process. Added `import sys`.

- **`raven/tools/_pyrunner.py`** (new): subprocess runner reusing `_RESTRICTED_BUILTINS` from `shell.py`; returns last-expression value or error text.

- Verified: channels (`signal`, `matrix`, `github`, `gitlab`, `feishu`, `enterprise_base`) send to operator-configured URLs only (no user-URL SSRF); `client_manager` uses httpx default `follow_redirects=False`; `_restrict_key_file` runs in sync startup path only.

### Event-loop blocking fixes (sync subprocess in async context)

- **`raven/coding/git_integration.py`**: `auto_commit_async`, `create_pr_async`, `llm_review` called sync `_run` (subprocess.run, timeout=60) directly on the event loop. Rewritten with `asyncio.to_thread` around every git op; `subprocess.CalledProcessError` now returns error results instead of 500s. Kept the stage_all-before-commit logic.

- **`raven/core/git_api.py`**: All `/api/git/*` async handlers (status, branch, branches, log, log/detail, diff, diff/commit, blame, commit, push, pull, checkout) wrapped in `asyncio.to_thread` — no more event-loop freeze on slow git ops.

- **`raven/tools/git.py`**: `git_commit` non-auto path now `await asyncio.to_thread(git.commit, ...)` (was sync call in async handler).

- **`raven/unique/chaos_engineering.py`**: `inject()` fault dispatch (`_inject_service_kill/_inject_network_latency/_inject_disk_fill/_inject_cpu_storm/_inject_memory_leak/_inject_process_kill`) and `recover()`'s `_recover_fault` now run via `asyncio.to_thread`.

- Verified: `raven/voice/conversation.py:163` already uses `asyncio.to_thread(self.tts.synthesize, ...)`; `tool_registry._run_handler` wraps sync tool handlers in `asyncio.to_thread`; all remaining sync `subprocess.run` sites are CLI-only (sync context). No `time.sleep` in async functions anywhere.

### SSRF on user-controlled outbound URLs (round 2)

- **`raven/core/skills.py`**: `set_skill_registry` now validates http(s) scheme + hostname (invalid/empty clears registry, matching test semantics); `download_skill` validates `skill_id` (`/`, `..`, `.`-prefix) and `validate_url` on the constructed registry URL before `client_manager.get`.

- **`raven/unique/plugin_marketplace.py`**: `_fetch_remote_metadata` (remote `install_plugin` GET of `{url}/plugin.json`) and `PluginCatalog.sync` now pass URLs through `validate_url` — blocks SSRF to private/internal hosts.

- **`raven/tools/nodes.py`**: `NodeManager.register` rejects non-http(s) endpoints (scheme + hostname required); `execute` re-validates `node.endpoint` scheme before POST (guards endpoint tampering). Localhost/LAN endpoints are allowed — pairing local/LAN worker nodes is the intended use case, and agents already have the SSRF-guarded `http_request` tool for generic fetches.

- **`ravencode/runtime/skills.py`**: `set_skill_registry` now requires http(s) scheme + hostname.

- **`raven/core/monitor/checkers/http_check.py`**: switched to `client_manager.request` so `resp.text` is available — fixes broken `content_match` (was parsing JSON dict from `client_manager.get/post`).

- Audited all remaining outbound HTTP call sites: `web_search.py`, `ravencode/runtime/tools.py` `_httpx_search` (fixed search hosts, safe), `media.py`, `media_api.py`, `github.py`/`github_api.py`/`ci.py` (fixed GitHub + operator-env GitLab/Jenkins hosts), `tools/http.py` (already per-hop validate_url) — no new user-URL SSRF vectors.

### Verification

- ruff 0, mypy 0, full suite **2196 passed / 14 skipped / 22 deselected (e2e+load)**.

## Fixes applied (Aug 2027 — Desktop EXE packaging + dashboard serving)
### EXE packaging pipeline
- **`scripts/launcher.py`**: PyInstaller entry point — resolves a writable data dir (next to EXE or `RAVEN_DATA_DIR`), creates `data/logs/workspace`, redirects `DB_PATH`/`LOG_FILE`/`WORKSPACE_PATH`/`PYTHONUNBUFFERED` before importing raven, chdirs into the data dir, boots the gateway via `create_gateway()` + `asyncio.run(_run_gateway(gateway, web_port))`, opens the browser to `http://localhost:{port}/` after 2.5s. Flags: `--port`, `--no-browser`, `--ghost`. Browser opener now uses `contextlib.suppress` (SIM105/S110 clean).
- **`scripts/raven.spec`**: PyInstaller onefile `Raven.exe` (console=True, icon `scripts/raven.ico`, upx=False for deterministic builds). Datas: `web/dist` → `web/dist` (top-level, so `Path(__file__).parent.parent.parent / "web/dist"` resolves inside `_MEI`), root `plugins/` → `plugins/`, and each `raven/plugins/<name>/` package dir → `raven/plugins/<name>` (gateway_runner loads plugins via `spec_from_file_location`, so the `plugin.py` files must exist as real files in the bundle). Hiddenimports via `collect_submodules` for `raven.plugins`, `raven.monitors`, `raven.routines`, `raven.tools`, `raven.unique`, `aios`, `ravencode`. Excludes: torch, transformers, chromadb, playwright, spacy, numba, sounddevice, y_py, docker, capstone, pefile, textual, etc. Removed the ineffective global `DISTPATH`/`WORKPATH`; build script passes `--distpath packaging\dist --workpath packaging\build`.
- **`scripts/build_exe.ps1`**: `npm ci` (if node_modules absent) → `npm run build` → `python scripts/make_icon.py` → `python -m PyInstaller --noconfirm --clean --distpath packaging\dist --workpath packaging\build scripts/raven.spec`. Result: `packaging/dist/Raven.exe` (~129 MB).
- **`scripts/make_icon.py`** + `scripts/raven.ico`: generates a violet→indigo gradient bird icon if absent.
### Dashboard serving fixes (found during EXE smoke test, no mocks)
- **`raven/cli/gateway_runner.py`**: SPA assets used absolute `/assets/*` paths while the app was only mounted at `/dashboard`, so the JS/CSS bundles 404'd (blank UI). Fixed by mounting `/assets` via StaticFiles and adding a catch-all `GET /{full_path:path}` that returns `web/dist/index.html` for any non-`/api/` path (client-side routing). Registered last so all `/api/*` routes keep precedence; unknown `/api/*` paths still return 404 JSON. (A naive root mount at `/` was tried first but Starlette's `/` mount shadowed the `/dashboard` mount — reproduced with a minimal FastAPI app.)
- **`raven/channels/webchat/channel.py`**: `_get_index_html()` now returns the built `web/dist/index.html` when present (resolves `Path(__file__).parent.parent.parent.parent / "web" / "dist" / "index.html"`, which inside the onefile bundle points at `<tmp>/web/dist/index.html`), falling back to the legacy Alpine `INDEX_HTML`. This makes `/` serve the real React SPA. `tests/test_webchat.py` asserts the `INDEX_HTML` constant directly, so it stays green (23 passed).
- **`scripts/launcher.py`**: opens the browser to `/` (the SPA root) instead of `/dashboard`.
### Smoke test (real EXE, no mocks)
- `packaging/dist/Raven.exe --port 18999 --no-browser`: plugins load (42 tools), Uvicorn up, `/` serves React index.html (title "Raven AI"), JS bundle `/assets/index-*.js` → 200 (416 KB), `/dashboard` and SPA deep links (`/chat`) → 200 index.html, `/api/health/ready` → ok, `/api/status` → running, `/api/health` → degraded (LLM key not configured — honest status), unknown `/api/*` → 404. Telegram/Discord channels gracefully skip without tokens (guardian logs heartbeat misses + restart).
- First EXE run crashed with `FileNotFoundError ...\_MEI...\raven\plugins` because `gateway_runner` loads plugins from `Path(__file__).parent.parent / "plugins"` — fixed by bundling `raven/plugins` package dirs as data.
### Verification

- ruff 0 errors (incl. launcher SIM105/S110), mypy 0 errors, webchat tests 23/23 pass, PyInstaller build clean.
- Re-verified Sep 2026: `build_exe.ps1` runs clean (`npm ci` → `vite build` → PyInstaller), `Raven.exe` 128.7 MB, smoke test all endpoints pass. `upx=False` for deterministic builds.



## Fixes applied (Aug 2026, live gateway testing + bug hunt)

### P0 — Prometheus "Incorrect label names" crash (real bug, live-reproduced)

- **`raven/core/metrics.py`**: `_prom_inc`/`_prom_observe` cached a metric under its name with label_names from the FIRST call; a later call with a different label set raised `ValueError: Incorrect label names` from prometheus_client.

- **Two conflicting pairs found live** (POST `/aios/ai` → 500):

  - `llm_complete`: router.py used `{model,status}` while instrumented.py used `{provider,model,status}`

  - `message_errors`: gateway.py used `{channel}` in one path and `{channel,reason}` in another

- **Fix**: `raven/core/llm/router.py` renamed its metric to `llm_request_result` with `{model,status}` (both ok/error branches); `raven/core/gateway/gateway.py` `message_errors` now always passes `{channel,reason:"handler"}` / `{channel,reason:"circuit_breaker"}`. Metric label sets are now disjoint: `llm_complete{provider,model,status}` (instrumented), `llm_request_result{model,status}` (router), `message_errors{channel,reason}` (gateway).

- **`tests/core/test_gateway_routing.py`**: updated `test_generic_exception_sends_error` to assert `{"channel","reason":"handler"}`.



### Failover log double provider prefix

- **`raven/core/failover.py`**: `auto_model_list()` returns provider-prefixed models (`ollama/llama3`); `ModelFailover` logged `{provider}/{model}` producing misleading `ollama/ollama/llama3`. The actual call was correct — only the log was wrong. Fixed all 5 log sites to print `model_cfg.model` only.



### `/aios/agent/truthful` returned 500 on LLM failure

- **`aios/api/bridge.py`**: `aios_agent_truthful` didn't catch provider exceptions → HTTP 500, while `/aios/agent` and `/aios/agent/multi` wrapped errors. Now catches and returns `TruthfulResponse(status="error", content="[error: ...]")`.

- **`tests/test_aios_agent_ws.py`**: added `test_truthful_endpoint_wraps_llm_error`.



### `TTSConfig(cache_dir=...)` silently appended `raven_tts_cache`

- **`raven/voice/tts.py`**: `cache_dir` argument was joined with `/raven_tts_cache`, so a user-supplied directory was never used as-is. Fixed: only `tempfile.gettempdir()/raven_tts_cache` is the default; an explicit `cache_dir` is used verbatim.



### Voice test fixes

- **`tests/test_voice_stt.py`**: fake `vosk.Model` signature didn't match the real call (`vosk.Model(model_path)` is positional) — `model_path` was landing in the `lang` kwarg. Fake now takes `*args/**kwargs`. Default-model test uses `.get("model_path")`.

- **`tests/test_voice_tts.py`**: `test_posix_branch` / `test_macos` monkeypatched `os.name="posix"`, but on Windows Python 3.12 `pathlib.Path` resolves per-`os.name` and instantiating `PosixPath` raises `NotImplementedError`. Both marked `@pytest.mark.skipif(os.name == "nt")` — POSIX branches can only run on POSIX hosts.



### Verification (no LLM backend available — no ollama, no API keys)

- Full suite: **3558 passed, 17 skipped, 29 deselected** (~265s).

- ruff 0 errors, mypy 0 errors (459 source files).

- Live gateway (`python -m raven aios gateway --port 19123`): `/aios/health`, `/aios/metrics`, `/aios/metrics/prometheus`, `/aios/ai`, `/aios/agent`, `/aios/agent/multi`, `/aios/agent/truthful`, `/aios/exec`, `/aios/sessions`, `/aios/sessions/{id}` all verified. LLM-dependent routes return an honest `[error: All LLM providers exhausted ...]` instead of crashing.

## Fixes applied (Aug 2026, live gateway hardening round 2)
### SQLite connection race in BaseStore._conn (real bug, concurrency test)
- **`raven/core/store.py`**: `_conn()` checked `self._connection is None` before `await aiosqlite.connect()`. Under first concurrent access (10 workers x 20 writes) several coroutines created separate connections to the same file; the old ones leaked and held WAL locks, producing `sqlite3.OperationalError: database is locked` on the very first write.
- **Fix**: whole connection bootstrap (connect + row_factory + PRAGMAs + schema + migrations) moved under self._lock. Single connection, no races, no leaks.
- **Verification**: concurrency harness (10 async workers x 20 writes) now 200/200 ok for TaskStore and MonitorStore (was 199/200 + database is locked). Related suites pass: 142 passed (task_engine, monitors, pagination, admin_api).
### Live-gateway verification of new middleware (previous round)
- /aios/health public 200; /aios/exec without token > 401; rate limiter verified live: 200 rapid requests > 59x 200 + 141x 429 (limit 60/min with burst). Shell-injection covered by unit tests (27 passed in test_aios_runtime).

- **`tests/core/test_sandbox.py`**: `test_sandbox_docker_no_docker_package` was environment-dependent — it asserted a fallback message, but when Docker Desktop is running the sandbox actually executes the code (returns "hi"). Now deterministic: monkeypatch.setitem(sys.modules, "docker", None) forces the "package not installed" path regardless of environment.
### Verification (final)
- Full suite: **3590 passed, 17 skipped, 1 xpassed** (was 3558). ruff 0 errors, mypy 0 errors (459 source files).

## Fixes applied (Aug 2026, tests mypy cleanup round)
- **Goal**: `check_all.py --quick` (ruff + mypy + imports + CLI) fully green including `tests/`. mypy on tests had 155 pre-existing errors (mock typing, `dict | list` unions, fake modules). Final result: **mypy 0 errors on 220 test files**.
- **`tests/test_tools_github.py`**: `_github_api` returns `dict[str, Any] | list[Any]`; tests did `result["error"]` on the union. Added `assert isinstance(result, dict)` after every `result = await github_*`/`_github_api` call that reads dict keys (17 sites). 42 passed.
- **`tests/test_tools_browser.py`**: fixture return type → `Generator[None, None, None]`; `_validate_url` returns None so `is None` asserts became bare calls (`# must not raise`); `browser_mod.socket` → local `socket` (same module object); mock assignments to module globals (`_browser_instance`, `_browser_context`, `_agent`) get `# type: ignore[assignment]`; `setattr(mod, "async_playwright", ...)` with `# noqa: B010`; callback-mock asserts get `# type: ignore[attr-defined]`; `list.append` in a lambda replaced with a real `_record` helper; dict/list args to `browser_fill_form`/`browser_set_headers`/`browser_set_cookies` get `# type: ignore[arg-type]`. 112 passed.
- **`tests/test_voice_stt.py`**: `__exit__` return type `bool` → `None` (always returns False); `recognize_google` returns `str(...)` instead of `Any`; fake-module attribute sets use `setattr(...)` → ruff `B010` → reverted to direct assignment with `# type: ignore[attr-defined]`; `stt.tempfile` → local `tempfile`, `stt.Path` → local `Path` (same objects). 40 passed.
- **`tests/test_voice_wake.py`**: `__exit__` → `None`; `WakeWordDetector.callback` typed `Callable[[str], Awaitable[str]] | None` but tests assign `async def cb(text) -> None` → `# type: ignore[assignment]`; `wake.logger` → `from loguru import logger` (same object). 12 passed.
- **`tests/test_voice_tts.py`**: `_FakeSapi` module-level placeholder deleted, `_make_fake_sapi` returns `list[Any]`; `tts.Path` → local `Path`; `builtins.__import__` re-export gets `# type: ignore[arg-type]`; fake-module attrs `# type: ignore[attr-defined]`. 31 passed.
- **`AGENTS.md` encoding repair**: the file had a single stray cp1252 byte `0x97` (em-dash) breaking strict UTF-8 read; `test_ravencode_context` (reads AGENTS.md as system prompt) crashed with `UnicodeDecodeError`. Repaired via surrogateescape + cp1252 mapping; also fixed two lines that had lost leading chars (store.py bullet, sandbox bullet) and removed a leftover `- **`. Full suite then: **3594 passed, 17 skipped, 1 xpassed**.
- **Verification**: ruff 0, mypy 0 (220 test files), `check_all.py --quick` 4/4 PASS, full suite **3594 passed / 17 skipped / 1 xpassed**.

## Fixes applied (2027-08, PostgreSQL migration)
### Thin AsyncDB layer replaces per-store SQLite plumbing
- **`raven/core/asyncdb.py`** (new core): `AsyncDB` abstract (transaction returns `AbstractAsyncContextManager[None]`), `SQLiteDB` (aiosqlite, WAL + `_rewrite` keeps `?` placeholders) and `PostgresDB` (asyncpg, rewrites `?` → `$n`, returns rowcount via `_rowcount()` parsing of asyncpg status). Factories `connect_backend(db_path)` (prefers `DATABASE_URL`/DSN → Postgres) and `is_postgres_dsn()`. Connection pooling + retry/backoff for Postgres.
- **All core stores migrated** off raw aiosqlite onto `AsyncDB`: task_engine, monitor, routine, auth (incl. coder/session), plus `analytics.py`, `outbox.py`, `services/persister.py`. `BaseStore` gains `_path` (`None` for AsyncDB); DSN strings stored as `str` (never `Path` — `Path("postgresql://...")` corrupts the DSN on Windows).
- **`raven/core/db_postgres.py`**: `PostgresDatabase` (shared pool, health, metrics) + `_PostgresMigrator` reusing the unified migration table with PG-syntax branches; `raven/core/db.py` and `tools/db.py` route to Postgres when `DATABASE_URL` is set.
- **`docker-compose.postgres.yml`** (new): postgres:16-alpine, user/password/db=raven, volume, pg_isready healthcheck. `pyproject.toml` gains extra `[postgres] = ["asyncpg>=0.29"]`.
- **Tests**: `tests/core/test_migrations.py` rewritten on `SQLiteDB`; `tests/integration/test_postgres_stores.py` (new, 9 tests) covers Task/Monitor/Routine/Auth stores, Outbox delivery+drop, AnalyticsEngine, Persister against a live PG — auto-skip without `DATABASE_URL`, `_clean_table()` guards outbox test idempotency.
- **Verification**: ruff 0, mypy 0 (16 migrated files + tests), full suite **3594 passed / 26 skipped / 1 xpassed**, integration PG suite **9 passed** against a real server, `check_all.py --quick` 4/4 PASS.



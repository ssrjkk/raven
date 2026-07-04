# Agent Guidelines

## General
- Type hints required for all Python functions
- Use `loguru` for logging, never `print`
- No docstrings unless logic is non-obvious
- Prefer `pathlib` over `os.path`
- Error handling: raise exceptions, never mask with string returns
- Async first: all I/O operations must be async

## Module structure
- `raven/` — core engine (Telegram, LLM, channels, tools)
- `ravencode/` — high-level Python API for AI agents
- `aios/` — thin FastAPI bridge (delegates to ravencode)
- `web/` — React SPA (Vite + Tailwind)
- `desktop-tauri/` — Tauri desktop shell
- `packages/` — TypeScript shared packages
- `tests/` — pytest tests (unit + integration)

## Setup
```powershell
# Python backend
pip install -e ".[dev]"

# Web frontend (requires Node.js)
cd web
npm install
cd ..

# Desktop (requires Rust)
cd desktop-tauri
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
- Run `python scripts/test_imports.py` before commit
- Run `ruff check raven/ aios/ ravencode/` before commit
- Run `python -m mypy raven/ aios/ ravencode/ --ignore-missing-imports` before commit (target: 0 errors)
- Run `python -m pytest tests/ -q` before commit
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

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

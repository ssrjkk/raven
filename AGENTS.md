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
- `scripts/` — build/dev tooling (incl. `raven.spec`, `build_exe.ps1` — the only PyInstaller spec)
- `extension/` — browser extension (MV3) + `extension/vscode/`
- `deploy/`, `docs/`, `packaging/` — infra, docs, EXE build output

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
- pyproject `addopts` enables coverage (gate: 60%, `.coveragerc`) + allure; for a single test file use `pytest <path> --no-cov` to skip the gate
- Full suite: ~4900 tests, ~11 min. Frontend: `cd web && npx tsc --noEmit && npm test -- --run`
- EXE packaging: `scripts/build_exe.ps1` (uses `scripts/raven.spec`; output in `packaging/dist/`)
- Record notable changes in `CHANGELOG.md` — do not grow this file with fix logs

## History
Past fix logs (2026 session notes, previously kept in this file) are archived verbatim in `docs/archive/fixes-history.md`. They may reference files that no longer exist; the working tree and `CHANGELOG.md` are authoritative.

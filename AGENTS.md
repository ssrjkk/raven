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
- Run `python -m pytest tests/` before commit
- Never commit secrets or .env files

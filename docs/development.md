# Development

_by [@ssrjkk](https://github.com/ssrjkk)_

## Setup

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
pre-commit install
```

## Project Structure

```
raven/
├── channels/          # 15 messaging channel adapters
├── cli/               # Click-based CLI (26 command groups)
├── coding/            # Coding assistant, git integration
├── core/              # Core engine
│   ├── gateway/       # Message orchestrator
│   ├── agents/        # Agent system, orchestrators, profiles
│   ├── security/      # Policy engine, sandbox, SSRF, PII redaction
│   ├── task_engine/   # Task planning & execution
│   ├── monitor/       # HTTP, price, RSS, file, process monitors
│   ├── rag/           # Embeddings, BM25, JSON vector store
│   ├── llm/           # LLM providers, failover, circuit breaker
│   ├── config.py      # Settings (env cascade)
│   └── asyncdb.py     # SQLite/PostgreSQL abstraction
├── gateway/           # Gateway glue, channel guardian
├── plugins/           # 10 built-in plugin packages
├── routines/          # Scheduled routines
├── tools/             # 66 assistant tool registry
├── tui/               # Textual TUI
├── voice/             # TTS/STT module
└── workspace/         # Workspace manager, plugin loader

ravencode/             # Autonomous coding agent (runtime, agents, cli)
aios/                  # Thin FastAPI AI-gateway bridge
web/                   # React 19 + Vite dashboard
tests/                 # Test suite
docs/                  # Documentation
deploy/                # Docker, systemd, observability, traefik
```

## Development Loop

```bash
# Quick validation gate (ruff + mypy + imports, no tests)
python scripts/check_all.py --quick

# Full gate (lint + types + imports + all tests + frontend build)
python scripts/check_all.py

# Lint
ruff check .

# Test
pytest tests/ -q --tb=short

# Run gateway
raven start

# Run TUI
raven tui
```

## Testing

```bash
# Run all tests
pytest tests/ -q --tb=short

# Run with coverage
pytest tests/ --cov=raven --cov-report=term-missing

# Run specific test file
pytest tests/core/test_sse.py -v
```

## Code Style

- Follow existing patterns in the codebase
- No unnecessary comments
- Type hints required for all function signatures
- Async-first for I/O operations
- Use loguru for logging

## Web Dashboard Assets

The gateway serves the built React SPA from `web/dist`. It is auto-discovered (repo checkout,
installed wheel, PyInstaller bundle, or `RAVEN_WEB_DIST` override):

```bash
cd web && npm ci && npm run build   # produces web/dist
```

Wheel/sdist builds pick up the SPA when CI stages it inside the package (`raven/web/dist`) —
see `.github/workflows/pypi.yml`; the Docker image builds it in a dedicated stage and points
`RAVEN_WEB_DIST` at it.

## Icons

```bash
python scripts/make_icon.py                 # scripts/raven.ico (skipped if present)
python scripts/make_extension_icons.py      # extension/icons/*.png + extension/vscode/icon.png
```

## Building

```bash
pip install build
python -m build
```

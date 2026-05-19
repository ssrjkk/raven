# Development

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
├── channels/          # Messaging channel adapters
│   ├── telegram/
│   ├── discord/
│   ├── slack/
│   ├── whatsapp/
│   └── ...
├── cli/               # CLI commands
│   ├── main.py        # Click-based CLI
│   ├── onboard.py     # Setup wizard
│   └── service.py     # Service management
├── core/              # Core engine
│   ├── gateway/       # Message orchestrator
│   ├── agent/         # Agent system
│   ├── security/      # Policy engine, audit
│   ├── task_engine/   # Task planning & execution
│   ├── llm.py         # LLM router
│   ├── config.py      # Settings
│   ├── sse.py         # SSE streaming
│   ├── tracing.py     # OpenTelemetry
│   └── self_heal.py   # Health monitoring
├── plugins/           # Plugin tools
├── tools/             # Built-in tool registry
├── tui/               # Textual TUI
├── voice/             # TTS/STT module
└── routines/          # Cron routines

web/                   # React frontend
tests/                 # Test suite
docs/                  # Documentation
deploy/                # Deployment configs
```

## Development Loop

```bash
# Lint
ruff check .

# Test
pytest tests/ -q --tb=short

# Run gateway
raven start --verbose

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

## Building

```bash
pip install build
python -m build
```

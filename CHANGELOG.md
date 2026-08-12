# Changelog

All notable changes to Raven AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-06-05

### Added
- Web frontend: Login page, 404 page, Toast notification system, loading skeletons
- Auth flow: ProtectedRoute wrapper, Bearer token management, 401 auto-redirect
- CI: web-build job for frontend build/lint
- `.env.example`: NATS, JWT, OTEL, Qdrant, LLM API key, and 15+ new configuration variables
- `tokens.schema.json` design token schema with `$schema` validation
- TypeScript base config (`packages/package.json`, `web/tsconfig.json` extends)

### Fixed
- All 4 Python service Dockerfiles: `python:3.14-alpine` → `python:3.13-alpine`
- CI Python version: 3.14 → 3.13; added `pip install -e .` for lint/test jobs
- Rust daemon: `Disks::new_with_refined_list()` → `Disks::new()` (deprecated API)
- Rust daemon: cross-platform `stop_daemon` with Windows taskkill support
- Go module version: `go 1.25.0` → `go 1.26` in monitor-engine
- pyproject.toml: removed `daemon/` from wheel packages (Rust code, not Python)
- Dependency version sync across `requirements.txt`, `pyproject.toml`, `monolith-requirements.txt`

### Enhanced
- Frontend: converted IDE.tsx inline styles to Tailwind; Tailwind-safe grid in CanvasViewer
- Frontend: exponential backoff WebSocket reconnection with unmount guard
- Frontend: optimized Vite config (manualChunks, sourcemap, chunkSizeWarningLimit)
- Frontend: SEO meta tags, CSP headers, preconnect for Google Fonts in index.html
- Frontend: tool messages visible, system messages not truncated in Chat view
- Frontend: auto-scroll to new messages in Chat

### Removed
- Dead Sidebar.tsx component (unused)
- Duplicate CSS variables from index.css (now sourced from tokens.json via ThemeContext)
- Unused `react-syntax-highlighter` / `@types/react-syntax-highlighter` dependencies

## [Unreleased]

### Added
- Voice module: TTS (ElevenLabs, gTTS, system) and STT (Whisper, speech_recognition)
- Web admin dashboard: model config, channel management, live logs, security audit UI
- Default workspace prompt files: AGENTS.md, SOUL.md, TOOLS.md
- Pre-commit hooks configuration (.pre-commit-config.yaml)
- Project security policy (SECURITY.md)
- Contributing guide (CONTRIBUTING.md)
- Docker configuration (.dockerignore)
- PyPI publishing configuration (pypi.yml workflow)
- MkDocs documentation site structure
- CI matrix expansion: Python 3.11, 3.12, 3.13 across ubuntu, windows, macOS
- PostgreSQL backend: thin `AsyncDB` layer (`raven/core/asyncdb.py`) with `SQLiteDB` and `PostgresDB` backends — all core stores (tasks, monitors, routines, auth, sessions, outbox, analytics, persister) run against Postgres when `DATABASE_URL` (or a `postgresql://` DSN `db_path`) is set
- `raven/core/db_postgres.py`: `PostgresDatabase` (shared pool, health, metrics) + `_PostgresMigrator` using the unified migration table
- `docker-compose.postgres.yml` for local Postgres (postgres:16-alpine, user/password/db=raven)
- `[postgres]` extras in `pyproject.toml` (`asyncpg>=0.29`)
- Integration test suite `tests/integration/test_postgres_stores.py` (9 tests, auto-skip without a live Postgres)
- LLM request queue with ordering + batching (`raven/core/llm/queue.py` + tests)
- Test suites for tool packages, voice (STT/TTS/wake) and session store
- MkDocs navigation for CLI, plugins, security and sprint-1 docs

### Enhanced
- Security audit: 23 standard + 8 deep checks with fix hints
- SSE streaming: backpressure (drop/block/throttle), Last-Event-ID replay, per-session metrics
- Rate limiter: burst multiplier, automatic IP blocking, is_blocked() API
- Input sanitization middleware: JSON depth limit, non-string key rejection
- Self-heal module: configurable health checks, exponential backoff restart
- `PostgresDB.execute` returns rowcount (parsed from asyncpg status), `?` placeholders rewritten to `$n`
- Postgres connection pooling with retry/backoff; `is_postgres_dsn()` guard so DSN strings are never wrapped in `Path` on Windows

### Changed
- All async tests migrated to `@pytest.mark.asyncio` pattern (no `asyncio.run()` in test files)
- `tests/core/test_migrations.py` rewritten on `SQLiteDB`

### Verification
- ruff 0, mypy 0, `check_all.py --quick` 4/4 PASS
- Full suite: **3594 passed, 26 skipped, 1 xpassed**; PG integration suite **9 passed** against a live server

## [0.3.0] - 2026-05-18

### Added
- Multi-channel support: Telegram, Discord, Slack, WhatsApp, Matrix, IRC, Signal, Google Chat, Feishu, LINE, Teams, WebChat
- LLM Router with model failover (OpenAI, Anthropic, OpenRouter, Ollama)
- Agent system with multi-agent routing and session isolation
- Security framework: policy engine, PII redaction, context filtering, tool policies
- Audit trail: event logging with rotation, signing verification
- Plugin system: file, code, memory, browser, API, process, git, cron, OCR, sessions
- Tool registry with 10+ built-in tool categories
- Task engine with planning, execution, monitoring
- Cron-based routines (briefing, file watch)
- Active monitoring system (HTTP, price, RSS, file, process)
- Textual TUI dashboard with live stats
- Design tokens system (JSON + Python + CSS vars)
- OpenTelemetry tracing with LLM and tool call instrumentation
- Linux sandbox detection (seccomp, nsjail, cgroups v2)
- Cross-platform service management (Windows, systemd, launchd)
- CLI: start, stop, status, doctor, onboard, agent, send, pairing, service, task, monitor, code, routine, tui
- WebChat interface with WebSocket streaming
- SSE event streaming for real-time updates
- Webhook system (Slack, WhatsApp, Google Chat, Signal, Teams, Feishu, LINE)
- Rate limiting with per-IP sliding window
- JSON input sanitization middleware
- Self-healing service health monitoring
- 438+ unit tests across all modules

### Security
- DM pairing policy (pairing/open/closed)
- Tool execution security levels (deny/ask/full)
- Workspace-only file access enforcement
- Context visibility controls (all/allowlist/allowlist_quote)
- Secret scanning and API key validation
- CORS configuration audit
- Sandbox isolation for third-party plugin execution

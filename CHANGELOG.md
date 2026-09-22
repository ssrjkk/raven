# Changelog

All notable changes to Raven AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.8] - 2026-09-22

### Changed
- Version bump to 0.4.8 across all modules (pyproject.toml, Dockerfile, TUI, API servers, MCP clients, deploy configs)

### Removed
- All git tags — single `main` branch is the only release surface; Docker images are rebuilt on demand via manual Deploy dispatch (`ghcr.io/ssrjkk/raven:latest`)
- Duplicate `release` job from `deploy.yml` — GitHub Releases are owned solely by `release.yml`

## [0.4.7] - 2026-09-21

### Fixed
- CI: removed pinned SHA digest from Docker base image (digest no longer exists on Docker Hub)
- CI: disabled Docker build cache to prevent stale layer issues
- CI: fixed `.dockerignore` to allow `README.md` in build context
- CI: corrected action versions in PyPI workflow (v7/v6 → v4/v5)
- CI: made `uvloop` conditional with platform marker (`sys_platform != 'win32'`) for Windows compatibility
- CI: updated `trivy-action` from non-existent `0.29.0` to `@master`
- CI: disabled coverage check for Postgres integration tests (expected low coverage)
- Tests: updated `test_tools.py` assertion to match new error message ("Access denied" vs "outside workspace")

### Changed
- Version bump to 0.4.7 across all modules (pyproject.toml, Dockerfile, TUI, API servers, MCP clients, deploy configs)

## [Unreleased]

Condensed summary of ~280 commits since the 0.4.0 baseline (2026-06-05 → 2026-09-20). 2026 session fix logs: `docs/archive/fixes-history.md`.

### Added
- RavenCode agent core: streaming ReAct loop, typed LLM delta streaming (providers → router → client → agent → SSE/TUI/WS), parallel tool execution, tool-result cache, LLM retry with adaptive 429 limiter, context auto-compaction + deep digest compaction, repo map in system prompt, speculative pre-read with git co-change focus, queue priorities, usage/cost accounting, persistent memory tools, MCP tool wiring, Anthropic prompt caching, smart tool-result truncation with spill files, code search (BM25), run_tests tool, task-style eval suite
- Sub-agents: parallel delegation (`delegate_parallel`, `task_parallel`), auto checkpoint + `undo_changes`, subtask timeouts, LLM-based smart routing
- IDE/web: live agent streaming (WS tokens, tool trace, confirm dialog), voice input (Web Speech API), Agent Console page, full theme-aware UI redesign, command palette (Cmd/Ctrl+K), skeleton screens, accent color picker, project metrics dashboard, git diff/blame views, artifact renderer
- Reverse engineering module: binary analysis, disassembly (incl. RISC-V), strings, PE import fallback, ELF section entropy, toolchain detection, `lsp_diagnostics` tool
- PostgreSQL backend via unified `AsyncDB` layer (SQLite/asyncpg); DB indexes + migration v5; LLM request queue
- Packaging: PyInstaller EXE pipeline (`scripts/build_exe.ps1` → `Raven.exe`), SPA dashboard serving, landing page
- CI: unified `check_all.py`, E2E Allure job, Postgres integration job, EXE build job, secrets/CodeQL/dependency-review scans
- API test coverage: 30+ new test modules for core routers (email, AB testing, chaos, cost management, plugins, SSE, status, tests, voice, workflow, web search, etc.)

### Fixed
- 70+ fix commits: sandbox builtins isolation, auth on read endpoints, SSRF redirect-bypass hardening (`safe_fetch_async` per-hop validation), event-loop blocking (sync subprocess → `asyncio.to_thread`), Prometheus label conflicts, SQLite connection race, OAuth PKCE + exact redirect match, PBKDF2 600k + rehash, channel guardian restarts, Slack signature fail-open (see Security)

### Security
- `SlackChannel.verify_signature` now fails closed when `signing_secret` is not configured (previously returned `True`, accepting unsigned requests)

### Removed
- Dead `packages/` TypeScript tree (unused, untested, not in CI); broken `github/` action (dist never built); duplicate root `raven.spec`; `monolith-requirements.txt` / `requirements-dev.txt` (pyproject is the single source)
- 6 unused community-automation workflows (stats, triage, pr-review, notify-discord, close-stale, ravencode); kept CI/release/build/security workflows

### Changed
- AGENTS.md rewritten as concise guidelines (716 → 55 lines); historical fix logs archived verbatim to `docs/archive/fixes-history.md`
- README test count refreshed (4,900+); `docs/sprint-1.md` archived

## [0.4.0] - 2026-06-05

### Added
- Web frontend: Login page, 404 page, Toast notification system, loading skeletons
- Auth flow: ProtectedRoute wrapper, Bearer token management, 401 auto-redirect
- CI: web-build job for frontend build/lint
- `.env.example`: LLM API keys, channel tokens, OTEL, and 15+ configuration variables

### Fixed
- Web frontend: handling of removed Rust desktop app and Go microservices removed from the codebase
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
- MkDocs documentation site structure
- CI matrix expansion: Python 3.11, 3.12 across ubuntu, windows, macOS
- PostgreSQL backend: thin `AsyncDB` layer (`raven/core/asyncdb.py`) with `SQLiteDB` and `PostgresDB` backends — all core stores (tasks, monitors, routines, auth, sessions, outbox, analytics, persister) run against Postgres when `DATABASE_URL` (or a `postgresql://` DSN `db_path`) is set
- `raven/core/db_postgres.py`: `PostgresDatabase` (shared pool, health, metrics) + `_PostgresMigrator` using the unified migration table
- `docker-compose.postgres.yml` for local Postgres (postgres:16-alpine, user/password/db=raven)
- `[postgres]` extras in `pyproject.toml` (`asyncpg>=0.29`)
- Integration test suite `tests/integration/test_postgres_stores.py` (9 tests, auto-skip without a live Postgres)
- LLM request queue with ordering + batching (`raven/core/llm/queue.py` + tests)
- Test suites for tool packages, voice (STT/TTS/wake) and session store
- MkDocs navigation for CLI, plugins, security and sprint-1 docs
- Project Metrics dashboard (`/api/metrics/project`) with live workspace stats
- Command palette (Ctrl+K) with 28+ navigation commands and dynamic AI suggestions
- Git viewer with side-by-side diff and blame (`/api/git/*`)
- Accent color picker with theme customization

### Enhanced
- Security audit: 23 standard + 8 deep checks with fix hints
- SSE streaming: backpressure (drop/block/throttle), Last-Event-ID replay, per-session metrics
- Rate limiter: burst multiplier, automatic IP blocking, is_blocked() API
- Input sanitization middleware: JSON depth limit, non-string key rejection
- Self-heal module: configurable health checks, exponential backoff restart
- `PostgresDB.execute` returns rowcount (parsed from asyncpg status), `?` placeholders rewritten to `$n`
- Postgres connection pooling with retry/backoff; `is_postgres_dsn()` guard so DSN strings are never wrapped in `Path` on Windows
- Channel supervision: `ChannelGuardian` with heartbeats, per-channel/per-user rate limiting, auto-restart
- Docs aligned with the single-process monolith architecture (README, CONTEXT, docs/, specs/, marketing/)

### Changed
- All async tests migrated to `@pytest.mark.asyncio` pattern (no `asyncio.run()` in test files)
- `tests/core/test_migrations.py` rewritten on `SQLiteDB`

### Verification
- ruff 0, mypy 0, `check_all.py --quick` 4/4 PASS
- Full suite: **4677 passed, 17 skipped, 1 xpassed**; PG integration suite **9 passed** against a live server

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

# CHANGELOG archive: duplicate [Unreleased] block (pre-0.4.8 era)

Archived verbatim from `CHANGELOG.md` on 2026-09-29. The file carried two
`## [Unreleased]` sections; the current one is the condensed 0.4.0-baseline summary,
this one predates it. Nothing here is enforced by tests.

The text describes that era's working tree, not the current one. "CI matrix expansion
... across ubuntu, windows, macOS" never landed: `ci.yml` ran ubuntu only until the
Windows job was added, and macOS has no job.

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

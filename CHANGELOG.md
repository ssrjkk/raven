# Changelog

All notable changes to Raven AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A duplicate `## [Unreleased]` block from the pre-0.4.8 era is archived verbatim in
`docs/archive/changelog-pre-0.4.8-unreleased.md`.

## [Unreleased]

The detail for the 181 commits after the 0.4.8 bump (`5b21751`) is archived verbatim in
`docs/archive/changelog-unreleased-2026-11-16.md`. This section keeps the notable slice, as `AGENTS.md`
asks: the changelog is not a fix log.

### Added
- `raven doctor`, gateway credential relocation and provider resolution: the provider client notices its own credential moved, and a model name now has one answer to which provider it asks for
- `raven security promote USERNAME` — an install can mint the admin its login path can actually reach. `POST /api/auth/register` writes `role='user'` and `/api/auth/users` requires `admin:users`, so a fresh database had no reachable admin account
- MCP tool annotations state what each tool can do, taken from the policy that knows it rather than a hand-kept copy
- The fine-tuning loop runs, and its numbers mean what they claim
- The landing site is six pages; the gateway page publishes the command registry instead of a copy of it, and the docs audit fails on drift
- Every table says how it stops growing: `raven/core/retention.py` gives each of the 22 a lifecycle kind and the gateway sweeps telemetry on a timer behind five validated `RETENTION_*` knobs, while the build fails on a `CREATE TABLE` that has no decision next to it. What a person wrote is the conservative side — `RETENTION_HISTORY_DAYS=0` ships, so conversations, coding sessions and stored entities are deleted only when that knob is pulled

### Changed
- One UI language, with a command palette that still answers in Russian
- A central `workspace_root` replaces the per-module workspace caches
- The local gate runs the commands CI runs — eslint and the e2e TypeScript project included — says which stage died, and every CI job is bounded by `timeout-minutes`
- `npm run lint` runs eslint over `src` and `e2e` plus both TypeScript projects. It ran `tsc --noEmit` alone, so no eslint rule gated the script a developer actually types
- This changelog keeps the notable slice; the fix-log detail moved to `docs/archive/`, and a gate budgets the Unreleased section so it cannot quietly regrow
- The landing page has the type tiers it claims. Its two variable families now declare the weight range their file covers instead of one pinned face each, so the 18 headings that ask Space Grotesk 600 stopped rendering at 700, and the pitch line moved to a display tier measured against its own column rather than falling through to body size
- The hero arrives as a sequence — the six lines of the pitch 90ms apart, the console already on screen when the last lands. The wordmark needed its own rule to run the entrance and keep its 14s sheen: `.js .hero-copy > *` outranks `.hero h1`, so the sequence would otherwise have deleted the crawl
- The README band now shows the whole opening screen: `docs/screenshots/hero.png` is 1440x1030, the height the hero section ends at, because at 900 it cut the client config through its closing braces. The social card's alt names the three blocks its 1200x630 frame holds rather than the install row that starts at 655 and never appears

### Fixed
- The wake word could not survive its own capture file. One fixed name in the shared temp directory served every detector, so a second detector, another install of Raven or a temp cleaner that removed it between the write and the unlink sent `unlink` raising inside the retry branch — the transcription was already in hand, and the person never heard the word back. Each capture now gets its own file and its removal is its own cleanup.
- Postgres could not store its first conversation. Every writer binds `datetime.now(UTC)` while the schema declared `sessions`, `messages`, `users` and `secrets` timestamps as `timestamp without time zone`, which asyncpg refuses outright — measured on 16.14/0.32 as `DataError: can't subtract offset-naive and offset-aware datetimes`. No unit test of this backend could see it (they mock the driver) and no integration test reached those tables. The declared DDL now stores the offset, migration 13 converts an install already built on the old columns, the retention cutoff no longer strips the offset it is binding, and both the DDL text and the live catalog are gated so a naive column cannot come back.
- Console controls that reported success and changed nothing now reach real endpoints, and the palette navigates
- One handle could open two connections. `connect()` checked `_conn is None` and then awaited the open before assigning it, so a second coroutine reaching the same handle built its own connection — its WAL pragma answered `database is locked`, and the connection the handle dropped had no owner left to close it, which is what blocked the interpreter at exit. Both backends now serialise the open, and an absent table no longer aborts a whole retention pass
- The operator's tool switches bite on webchat and on task steps, not only on the path that had a test
- The shipped image can build the SPA it ships
- `raven service` on Windows installs a service that exists
- Every UTF-8 file is read back as UTF-8; committed text corruption was repaired and is now guarded
- Two console list endpoints stop leaking their SQLite connections
- A WebSocket frame sent during a reconnect is queued and flushed on open instead of dropped without a word, in both the agent and the chat hook. A full queue refuses visibly rather than dropping one level down
- A provider's `Retry-After` is capped (`LLM_RETRY_AFTER_CAP`, 30s) and clamped at zero, and the final attempt no longer sleeps before failing. The wait runs inside one of the ten admission slots, so `Retry-After: 86400` parked a tenth of the gateway's capacity for a day
- A collaboration session whose CRDT throws stops reporting `crdt_enabled` and stops handing out CRDT state. The fallback is a last-write-wins splice that does not merge concurrent edits, and the session used to keep claiming otherwise
- The documentation egress gate scans for a reference a browser would follow rather than for the hostname as a word. It failed on the archived changelog's sentence about taking Google Fonts out of the site — a gate that cannot tell a `<link>` from a description of one gets rewritten around instead of obeyed
- `scripts/capture_og_image.py` could not produce the frame its own gate asserts: it shot the `.hero` element, whose box is 943px tall at 1200 wide, so a 1200x630 card was unreachable and both screenshots had quietly stopped being re-shootable. It clips the viewport now, refuses a card whose opening sequence has not settled or whose frame cuts a block that card must hold whole, and re-reads the bytes it wrote
- An RSS monitor no longer reports its whole feed as new every time the gateway restarts. The entries it had already alerted lived in a process dict with a 7-day TTL, so a restart forgot them and the next poll alerted the feed from the top; the seen state is a `rss_seen_items` table now — one row per entry per monitor, written by the `ON CONFLICT DO NOTHING` insert that is itself the dedupe, so there is no read-then-write window left to lose. A monitor's first-ever poll baselines the feed instead of alerting it, and how long an entry stays seen is `RETENTION_TELEMETRY_DAYS` and `RETENTION_TELEMETRY_ROWS`, the two knobs that already bound every other telemetry

### Security
- Both `/mcp` routers refuse a denied tool on `POST /mcp/tools/{name}` as they already did on `/mcp/rpc`. A gate discovers every router module by scanning the tree, so a third one cannot stay permissive by being forgotten
- `GET /mcp/events` requires authorization
- A verification credential is spent once, and an unenforceable CORS policy is refused
- Tool errors stay out of responses
- Extension popup links accept only absolute http(s); `qs` 6.17.1, Pillow and libpcre2 raised to releases that close their advisories
- A chat transcript exported into the working tree is no longer tracked, and root Markdown is opt-in in `.gitignore`, so a renamed export cannot reach a public commit again
- The messaging profile lost arbitrary file read. `files.read` takes any path inside the root, and on a default install the root is the launch directory that holds `.env`, so an admitted DM user could read the secrets the credential name table refuses and every one it does not name — measured on the pre-fix tree as `is_tool_allowed("files.read") is True` under `EXEC_SECURITY=full`. The profile now offers `api.http_get`, `memory.recall` and `browser.search`, `policy/tools.json` stopped claiming otherwise, and the fifth resolver — `raven/tools/tests.py`, whose `generate_tests` opens the source it is handed and puts it in a prompt — answers the credential rule like the other four.

### Removed
- `ravencode web` and its `--port 0` option: the server behind them served no static files, and the option never opened a random port
- Dead code with zero callers: `raven/channels/registry.py`, the `packages/` TypeScript tree, the `extension/extension.js` prototype, a duplicate root `raven.spec`, the legacy requirements files, six unused community workflows, and the landing's video-frame pipeline whose frames were never generated
- Dead README tails, the drifted shields.io badge row, and `.gitignore` entries for directories that no longer exist

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

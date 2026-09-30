# Changelog

All notable changes to Raven AI are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A duplicate `## [Unreleased]` block from the pre-0.4.8 era is archived verbatim in
`docs/archive/changelog-pre-0.4.8-unreleased.md`.

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
- `tests/test_version_consistency.py`: guards every declared version surface (packaging/CLI/MCP/TUI/API/web/extensions), manifest asset references and PNG icon dimensions
- `.env.example` parity guard + critical-model env-alias tests in `tests/core/test_config.py`
- `scripts/icon_render.py` (shared icon renderer) + `scripts/make_extension_icons.py` — browser and VS Code icons generated from the same design as `scripts/raven.ico`
- `extension/README.md` (layout, load/package instructions, icon regeneration)
- Dashboard packaging: the React SPA is now discoverable across deployments (`raven.core.spa.resolve_web_dist` — env override, package-local, repo, PyInstaller bundle, cwd), shipped in the Docker image (dedicated Node build stage + `RAVEN_WEB_DIST`) and bundled into wheels when CI stages it at `raven/web/dist`

### Fixed
- 70+ fix commits: sandbox builtins isolation, auth on read endpoints, SSRF redirect-bypass hardening (`safe_fetch_async` per-hop validation), event-loop blocking (sync subprocess → `asyncio.to_thread`), Prometheus label conflicts, SQLite connection race, OAuth PKCE + exact redirect match, PBKDF2 600k + rehash, channel guardian restarts, Slack signature fail-open (see Security)
- Version surfaces synced to 0.4.8: web SPA (`package.json` + lock), Chrome manifest, VS Code extension (package + lock) and the RavenFlow gateway (`1.0.0` → `0.4.8`); the sidebar badge no longer shows a hardcoded `0.2.0` fallback
- `RAVEN_CRITICAL_MODEL` / `RAVEN_CRITICAL_PROVIDER` / `RAVEN_CRITICAL_API_KEY` were documented but silently ignored (the fields read `CRITICAL_*`); both spellings now resolve, `CRITICAL_*` wins
- Chrome extension: `manifest.json` referenced `icons/icon{16,48,128}.png` which did not exist (broke `Load unpacked` and the `Extension` workflow `cp -r icons`); the VS Code manifest icon was missing too
- Web dashboard was built nowhere but the dev checkout: the Docker image and PyPI wheel served no SPA, and `pypi.yml` uploaded a `web-dist` artifact that was never consumed
- `raven/tools/reverse_engineering/patterns.py`: invalid `\u` escape inside a bytes literal (`b"Qt5\u0000"`) — a Python `SyntaxWarning` today and a hard `SyntaxError` under `-W error::SyntaxWarning`; now `b"Qt5\x00"`
- Undeclared runtime dependency: `raven/cli/nodes_cmd.py` imported `requests` (not in `pyproject.toml`), which broke the whole CLI on a clean install — now uses `httpx`; guarded by the new `tests/test_dependency_declarations.py`
- Security audit false positives: `api_keys` failed for `groq/*` models even with `GROQ_API_KEY` set, `dependency_audit` invoked the non-existent `pip audit` (and mis-parsed pip-audit JSON), `audit_signing` ignored the auto-generated `data/audit_signing_key.bin`
- DevOps hygiene: `install` script referenced release tarballs that are never published, `init.sh` created unused directories, `scripts/setup.sh` still built the removed Rust daemon/Electron app, `Makefile clean` was Windows-only, dead `.oxlintrc.json`
- Frontend lint debt: 32 ESLint errors (import order + stale `react-hooks` disable comments) — `npx eslint src` is clean and now enforced in CI along with `npm test`
- `run_tests` / `test_coverage` reported `Tests: unknown` whenever pytest did not wrap its counts line in a `== ... ==` banner (narrow terminals, `-q`, and the coverage-gate line all suppress it); the ravencode `run_tests` returned an empty summary in the same cases. Both tools now match the counts themselves and no longer run pytest with `-q`
- `tests/core/test_webhooks.py`: mypy `var-annotated` on the shared `body` dict, which failed `check_all.py` — and therefore CI — on `main`
- `security_audit._check_dependencies` ran `pip-audit` with no timeout, so a slow or blocked PyPI mirror hung the audit until pytest's per-test limit killed it (`tests/unit` failed in `test_audit_deep_includes_extra`). The check is now capped at 60 s and reports the timeout with a manual-run hint
- `tests/contract/conftest.py` guarded on `import pact`, but pact-python 2.x+ installs without the `Consumer`/`Provider`/`Like`/`Term` API `test_pacts.py` uses — the import succeeds and then the whole `tests/unit` batch aborted on a collection error. The guard now checks those names, and mypy skips `test_pacts.py` so the result no longer depends on which pact-python version happens to be installed
- `docs/security/overview.md` rewritten against the code: 13-layer enforcement table, the HTTP authentication/RBAC and response-header layers that were missing entirely, `exec_security` vs `exec_ask_mode` separated, all five sandbox policies listed with their real values (`code-exec` is network-allowlisted, not offline; `web-browsing`/`read-only` have no container backend), and two cited paths that no longer exist replaced
- `tests/core/test_llm_queue.py::test_timeout_does_not_corrupt_queue` failed only in the `tests/full` check. A 50 ms admission timeout left the recovery waiter ~30 ms of slack, which loses against a busy event loop under coverage tracing (it passed in the isolated `tests/core` batch). The timeout is now 0.5 s and the test waits until the waiter is actually queued, so only the three deliberate drains expire
- The two `run_tests` suite tests (`tests/test_tools.py`, `tests/test_ravencode_core_round7.py`) passed only on machines whose temp dir holds no pytest config. The inner run climbed out of the scratch directory, picked up an unrelated `pyproject.toml` and its `addopts`, and died on a usage error before printing any counts — `Tests: unknown` in a clean `.[dev]` env. The mini suites now carry their own `pytest.ini`, so rootdir and config stay inside the workspace the tool was given
- `test_coverage` asked pytest for a relative `coverage.xml` (written to the caller's cwd) but read it back from the target path, so any call with `path` set reported `Coverage: 0.0%` and left the report behind. The report path is now absolute under the target, and the function has a real test for it
- `tests/test_ravencode_browser.py::TestNavigate` reached `browser_navigate`'s SSRF check, which resolves the hostname through live DNS and fails closed when the resolver returns nothing — so both tests turned into `[denied]` assertions whenever the machine's resolver blinked (seen in a `tests/full` run; green in isolation and on the clean-env run). The navigate tests now stub `ssrf.validate_url` like the rest of the repo's navigate tests, and a new test pins the denial path itself
- `check_all.py` echoed only the last 30 lines of a failing pytest batch, which is the part *after* the assertion diffs, so a `tests/full` failure gave no clue what broke. On a non-zero exit it now prints from the `FAILURES` block to the end (totals and short summary included); passing batches keep the 30-line tail
- The Docker image shipped an incomplete package. Its builder stage copied only `raven/`, while `pyproject.toml` lists `raven`, `aios` and `ravencode` under `[tool.hatch.build.targets.wheel] packages` — and hatchling skips missing directories silently. So the wheel, and the image built from it, contained no RavenCode agent and no aios bridge, while `raven.gateway.daemon`, `raven.core.mcp.*`, `raven.channels.webchat.streaming` and `raven.cli.coding` import `ravencode` at module level. All three trees are copied now, and the final stage installs the wheel with pip instead of copying the builder's `site-packages`, which also dragged `build`, `hatchling` and their transitive deps into the runtime image

### Security
- `SlackChannel.verify_signature` now fails closed when `signing_secret` is not configured (previously returned `True`, accepting unsigned requests)
- Webhook signature verification fails closed across the board: generic, `slack/events`, WhatsApp and every `_verify_webhook_signature` consumer (Google Chat, Signal, Teams, Feishu, LINE, GitHub, GitLab, GitHub Actions, Allure) now reject unauthenticated requests when no signing secret (`WEB_SECRET_KEY` / `SLACK_SIGNING_SECRET`) is configured, instead of accepting them — previously any unauthenticated POST could reach the self-heal/QA actions
- `confine_path` resolves symlinks with `realpath` before the workspace check, so a link inside the workspace pointing outside can no longer escape the boundary
- `cryptography` floor raised to `>=50.0.0` (runtime `secrets` extra and `dev`). The old `dev` cap `<45.0` resolved to 44.0.3, which pip-audit reports 10 open advisories against (incl. PYSEC-2026-3552, fixed only in 50.0.0); 50.0.1 audits clean, its 70 crypto-dependent tests pass, and wheels exist for 3.11/3.12 on Windows and Linux
- CI `security` job is now a real gate. It audited the runner's own preinstalled packages — the project was never installed — and both steps ended in `|| true`, so a known vulnerability could not fail the build. It now installs `.[dev]`, audits exactly that freeze (`pip freeze --exclude-editable` + `pip-audit --strict --no-deps`) and fails on any finding
- Exception text no longer reaches HTTP response bodies (the four `py/stack-trace-exposure` CodeQL findings). `ravencode.runtime.tools.execute_tool_public` is the boundary variant of `execute_tool`: it returns a fixed `[execution_error] tool failed` instead of the handler's message, and every path that writes a tool result into a response now uses it — both MCP HTTP routers, both MCP stdio servers and the RavenFlow `POST /api/tools/{name}` route. The agent loop keeps `execute_tool`, whose detail the model needs to repair a failing call. `admin_api` `check_now` returns `{"ok": true, "triggered": bool}` rather than the alert text it collected
- The `ravencode` MCP HTTP router had no authentication at all on `/mcp/rpc`, `/mcp/tools` and `/mcp/tools/{name}`. Auth now lives in one place, `raven.core.mcp/auth.py::authorize_request` (Bearer token or `X-Raven-Key`, token manager first, constant-time secret compare), shared by both routers; the duplicated per-router checks are gone

### Removed
- Dead `packages/` TypeScript tree (unused, untested, not in CI); broken `github/` action (dist never built); duplicate root `raven.spec`; `monolith-requirements.txt` / `requirements-dev.txt` (pyproject is the single source)
- 6 unused community-automation workflows (stats, triage, pr-review, notify-discord, close-stale, ravencode); kept CI/release/build/security workflows
- `extension/extension.js` + `extension/package.json` — dead VS Code prototype superseded by `extension/vscode/` (stale API port, duplicate command manifest)

### Changed
- READMEs rebuilt as two files: `README.md` (English, primary) and `README.ru.md` (Russian mirror), each linking to the other. Both are rewritten from the current code — the old page carried a comparison table with ChatGPT/AutoGen, "enterprise"-tier marketing, stale counts (4,677+ tests, channels "15 + ещё 15"), and a demo section for a GIF that never existed. The four secondary translations (es/ja/ko/zh) are deleted: they were machine-mirrors of the same stale text and no longer loadable
- CI: `dependency-review.yml` listed `PSF` in `allow-licenses`, which is not a valid SPDX identifier, so the check failed on every pull request with `Invalid license(s) in allow-licenses: PSF` before reviewing anything; the license is dropped from the allow-list
- CI: `gitleaks/gitleaks-action` bumped v2 → v3 in `ci.yml` and `secrets-scan.yml` — v2 fails on every pull request with "GITHUB_TOKEN is now required to scan pull requests", so PR checks were red regardless of content
- CI: new `docker` job builds the image and asserts, inside the container, that `aios`, `ravencode`, `raven.gateway.daemon` and `raven.core.mcp.server` import and that the `raven`, `ravencode` and `ravenflow` console scripts exist. No other check looked at the shipped artifact, which is why the incomplete wheel above stayed invisible
- Deploy workflow: the Trivy scan runs with `ignore-unfixed: true`, so container alerts list only findings that have a released fix. The unfixed Debian entries it used to report could not be acted on and kept the alert count permanently high
- Dockerfile: the dead `playwright install chromium 2>/dev/null || true` step and the seven Chromium shared libraries removed from the base stage (the image installs nothing that needs them; the hint for restoring them is a comment in the base stage), pip and setuptools upgraded in the runtime image, OCI `description` label reworded
- AGENTS.md rewritten as concise guidelines (716 → 55 lines); historical fix logs archived verbatim to `docs/archive/fixes-history.md`
- README test count refreshed; `docs/sprint-1.md` archived
- CI: added a `windows-latest` job — `check_all.py --quick` (lint, types, imports, CLI) plus the workspace-isolation, ravencode-boundary and core security test files. Windows is the primary dev and packaging target and had no CI coverage at all
- CI: dropped the `develop` branch trigger; the repository has only `main`
- pytest `eval` marker registered in pyproject, silencing `PytestUnknownMarkWarning` for the eval suite
- Coverage floor raised 60% → 65%: `check_all.py --cov` measures 72% over `raven` in a clean `.[dev]` env, so the old gate tolerated a 12-point regression before failing
- CONTRIBUTING.md development loop now points at `scripts/check_all.py` (with `--quick` / `--cov` / `--component`) instead of the bare `ruff check .` / `mypy raven/ --strict` / `pytest tests/` commands, which did not match the gate CI runs; the mypy example lists the real target set, since `scripts/` is excluded in pyproject
- README dependency facts corrected across all six languages: `matrix-nio` replaced with Matrix over the HTTP API (no `nio` import exists in the channel), workflow count 15 → 10, test count → 5,100+
- Web sidebar version badge now reads `web/package.json` instead of a never-defined `VITE_APP_VERSION`
- Dependency security floors bumped to patched releases: `fastapi>=0.141.1`, `starlette>=1.3.1`, `anyio>=4.14.2`, `lxml>=6.1.0`, `Pillow>=12.3.0`, `python-dotenv>=1.2.2`, `soupsieve>=2.9.0`, `typing-extensions>=4.8` (verified in a clean venv)
- Authorship/branding by ssrjkk across packaging, CLIs (`--version`, `raven doctor`), web sidebar/offline page, extensions, docs and CI metadata

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

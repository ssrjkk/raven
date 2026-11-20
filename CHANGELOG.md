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
- Every payload the console is tested with is the server's own answer. `scripts/gen_api_fixtures.py` wires the routers the way `gateway_runner` wires them — a real `Database`, the real `ChannelManager` with the real webchat channel, `AgentRegistry.setup_defaults()` reached through `Gateway.start()`, the monitor engine from `register_all_monitors()` — asks `/api/status`, `/api/admin/system/status`, `/api/metrics` and `/api/monitor/list`, and writes `web/e2e/fixtures/api.ts` annotated with the SPA's own declarations, which is the pattern `gen_health_fixture.py` set for `/api/health`. Until then three e2e specs and `Dashboard.test.tsx` were typing those payloads by hand, and what they had invented included a `version` the product never shipped, metric keys `metrics.snapshot()` has never emitted, and a monitor row whose `effective_interval`, `group` and per-row `version` nobody had read from the server. `tests/core/test_spa_api_contract.py` holds the links a generator cannot: a hand-typed stub anywhere in `web/` fails the tree-wide scan, an edited fixture fails byte currency against a fresh router run, and a key renamed on either side fails the compile, because the emitted literal is typed by `StatusData`, `SystemStatusData`, `MetricsSnapshot` and `MonitorListData`
- MCP tool annotations state what each tool can do, taken from the policy that knows it rather than a hand-kept copy
- The fine-tuning loop runs, and its numbers mean what they claim
- The landing site is six pages; the gateway page publishes the command registry instead of a copy of it, and the docs audit fails on drift
- Every table says how it stops growing: `raven/core/retention.py` gives each of the 22 a lifecycle kind and the gateway sweeps telemetry on a timer behind five validated `RETENTION_*` knobs, while the build fails on a `CREATE TABLE` that has no decision next to it. What a person wrote is the conservative side — `RETENTION_HISTORY_DAYS=0` ships, so conversations, coding sessions and stored entities are deleted only when that knob is pulled

### Changed
- One UI language, with a command palette that still answers in Russian
- A central `workspace_root` replaces the per-module workspace caches
- The local gate runs the commands CI runs — eslint and the e2e TypeScript project included, and `npm ci` plus `tsc --noEmit` over the VS Code extension, which nothing had ever compiled outside publish time — says which stage died, measures the machine it runs on as a stage of its own (free commit charge, free disk, and a write-and-rename probe in the reporter's directory, because five reported code failures were six orphaned log tailers eating the commit charge), and every CI job is bounded by `timeout-minutes`
- `npm run lint` runs eslint over `src` and `e2e` plus both TypeScript projects. It ran `tsc --noEmit` alone, so no eslint rule gated the script a developer actually types
- This changelog keeps the notable slice; the fix-log detail moved to `docs/archive/`, and a gate budgets the Unreleased section so it cannot quietly regrow
- The landing page has the type tiers it claims. Its two variable families now declare the weight range their file covers instead of one pinned face each, so the 18 headings that ask Space Grotesk 600 stopped rendering at 700, and the pitch line moved to a display tier measured against its own column rather than falling through to body size
- The hero arrives as a sequence — the six lines of the pitch 90ms apart, the console already on screen when the last lands. The wordmark needed its own rule to run the entrance and keep its 14s sheen: `.js .hero-copy > *` outranks `.hero h1`, so the sequence would otherwise have deleted the crawl
- The README band now shows the whole opening screen: `docs/screenshots/hero.png` is 1440x1030, the height the hero section ends at, because at 900 it cut the client config through its closing braces. The social card's alt names the three blocks its 1200x630 frame holds rather than the install row that starts at 655 and never appears
- The console paints the scales the storefront already used. Corners run 4px controls, 6px panels, 8px raised cards, 12px feature cards; type runs 10/11/12/14/16/18/20/24/30 with a 72px display; weights stop at 700 because no shipped face draws more. 93 components moved off magic numbers — `text-[10px]`, `font-black`, a `rounded-xl` that had quietly meant 6px everywhere — and a rebuilt-bundle browser check reads those numbers back off the live app rather than off the token file
- Tailwind utilities can no longer be a second scale. `scripts/gen_theme_css.py` renders `web/src/styles/tailwind-theme.css` next to the pre-hydration sheet, so `rounded-lg` resolves against `tokens.json` instead of the library's default, and the private `--dt-radius-*` alias block is gone — it let a component name a token no theme publishes and stay invisible to the guard that checks tokens exist
- The two surfaces that never load the SPA bundle — the gateway's webchat page and the extension popup — embed the generated token region byte-for-byte for colour, corner, size and font stack, instead of the palette that had invented `#8b5cf6` as a button surface under white text at 4.23:1
- The product drew two different birds. `site/favicon.svg` is now the one mark and `scripts/icon_render.py` rasterizes it — polygons, plate colour, corner radius — so the Chrome popup, the VS Code panel, the PWA icons and `raven.ico` ship scaled renders of that drawing instead of a hand-drawn white blob on a gradient and two `<text>🐦</text>`. A guard compares every shipped raster against the vector at the size its manifest declares, and a recolour, a moved vertex, a non-square viewBox, a curve command, a mutated render and a flipped PNG each demonstrably fail it
- What a browser paints no longer states itself with a font glyph: 32 pictographs left the surfaces the sweep reads — console and extension icons became lucide marks, CSS shapes or words, the popup's status became a drawn 8px circle whose accessible name `setStatus` maintains — while Telegram and Discord replies and CLI output keep theirs, being another medium. The sweep is proved against one sample per block it forbids, so it cannot pass by reading nothing
- Five more design contracts fail the build rather than the eye: a type step the scale doesn't own, a font weight no shipped face can draw, a corner off the ladder, an offline literal where a token belongs, and a corner or type size handed to a JSX style object as a number — the class that let ten chart tooltips keep painting 8px after the ladder moved under them. The dynamic-token names that hide inside string-built var paths are covered too, and every one of these ships with a planted-violation proof that its detector reads the form it forbids
- The pointer wash the storefront gives its cards is in the four surfaces that are not the storefront. `site/landing.js` attaches a listener per card, which is right for a page whose cards are in the first HTML and wrong for a tree that remounts on every route: one delegated listener now answers the whole console, and the same device is in the extension popup, the VS Code panel and the gateway's own webchat page. Coordinates go through the CSSOM rather than a `style` attribute, so the card's own inline styles and the CSP are untouched, one `requestAnimationFrame` stands in front of the writes because a 120 Hz mouse fires `pointermove` faster than a frame paints, and `prefers-reduced-motion: reduce` takes the light away — a card half-lit from a last move is worse than a plain one
- The VS Code panel now paints the brand's own faces. It named `IBM Plex Sans` in its header and status line and shipped no file behind either, so the chrome of a Raven panel was rendered in whatever the reader's machine had; its `@font-face` region is generated against `${fontRoot}/` — the `asWebviewUri` of a directory the manifest grants and nothing else — and the eight woff2 its sheet asks for travel inside the package. Face regions, mirrored package bytes and the documents pasting them are now read from one registration table in `scripts/gen_theme_css.py`, so a surface that starts shipping faces without registering there fails `--check` and fails the sweep that asks which documents paste a region; the panel's own webview reader had to learn the second interpolation the host evaluates, since a document cooked against one unknown value is a document the byte-for-byte guard was comparing its own guess of

### Fixed
- Console controls that reported success and changed nothing now reach real endpoints, and the palette navigates
- One handle could open two connections. `connect()` checked `_conn is None` and then awaited the open before assigning it, so a second coroutine reaching the same handle built its own connection — its WAL pragma answered `database is locked`, and the connection the handle dropped had no owner left to close it, which is what blocked the interpreter at exit. Both backends now serialise the open, and an absent table no longer aborts a whole retention pass
- The operator's tool switches bite on webchat and on task steps, not only on the path that had a test
- The shipped image can build the SPA it ships
- `raven service` on Windows installs a service that exists
- Every UTF-8 file is read back as UTF-8; committed text corruption was repaired and is now guarded
- Two console list endpoints stop leaking their SQLite connections
- A WebSocket frame sent during a reconnect is queued and flushed on open instead of dropped without a word, in both the agent and the chat hook. A full queue refuses visibly rather than dropping one level down
- A provider's `Retry-After` is capped (`LLM_RETRY_AFTER_CAP`, 30s) and clamped at zero, and the final attempt no longer sleeps before failing. The wait runs inside one of the ten admission slots, so `Retry-After: 86400` parked a tenth of the gateway's capacity for a day
- A Postgres install could not save a message. Every writer binds `datetime.now(UTC)` and the timestamp columns declared `timestamp without time zone`, which asyncpg refuses with a DataError at the insert, so neither a session row nor a message row could be written — and the suite that owns that promise skipped whenever no server answered, which is how it stayed green. The Postgres schema declares `TIMESTAMPTZ` now, migration 13 converts the columns an existing install already made by reading that database's own catalog, and the sweep's cutoffs for those tables bind the instant rather than a naive datetime. All of it is executed against a real Postgres 16 on both shapes an operator can arrive with — an empty database and one created before the fix, 22 cases, nine columns converted — with the conversion read back in a `+09:00` session, because under a UTC server a migration that forgot `AT TIME ZONE 'UTC'` moves every stored instant by nine hours and still passes. Two more gates read the DDL instead of a server: no naive `TIMESTAMP` in any schema a Postgres backend can be handed, and each retention policy's cutoff shaped the way the column it ages actually stores time. And `pytest tests/integration`, or `-m integration`, now fails where nothing listens: a selection that ran nothing is not a pass
- A collaboration session whose CRDT throws stops reporting `crdt_enabled` and stops handing out CRDT state. The fallback is a last-write-wins splice that does not merge concurrent edits, and the session used to keep claiming otherwise
- The auth tables stored their epochs as `REAL`, which on Postgres is a 4-byte float whose steps at a 2026 epoch are about two minutes wide, so a session's expiry was decided by rounding in the type. That store was the one of seven without a Postgres schema of its own, so the SQLite DDL ran on both backends; it has a twin now, and the gate that reads which schema a store hands Postgres covers the next one that forgets
- The documentation egress gate scans for a reference a browser would follow rather than for the hostname as a word. It failed on the archived changelog's sentence about taking Google Fonts out of the site — a gate that cannot tell a `<link>` from a description of one gets rewritten around instead of obeyed
- `scripts/capture_og_image.py` could not produce the frame its own gate asserts: it shot the `.hero` element, whose box is 943px tall at 1200 wide, so a 1200x630 card was unreachable and both screenshots had quietly stopped being re-shootable. It clips the viewport now, refuses a card whose opening sequence has not settled or whose frame cuts a block that card must hold whole, and re-reads the bytes it wrote
- An RSS monitor no longer reports its whole feed as new every time the gateway restarts. The entries it had already alerted lived in a process dict with a 7-day TTL, so a restart forgot them and the next poll alerted the feed from the top; the seen state is a `rss_seen_items` table now — one row per entry per monitor, written by the `ON CONFLICT DO NOTHING` insert that is itself the dedupe, so there is no read-then-write window left to lose. A monitor's first-ever poll baselines the feed instead of alerting it, and how long an entry stays seen is `RETENTION_TELEMETRY_DAYS` and `RETENTION_TELEMETRY_ROWS`, the two knobs that already bound every other telemetry
- The VS Code chat panel shipped a page whose script could not compile. Its webview is a template literal, so the host consumes the escapes written in it before a document exists: backticks in a CSS comment ended the literal in the middle of the stylesheet, `split('\\n')` reached the browser as a split on a raw newline inside a string, and a regex class written `\w` lost the backslash that makes it a class. The panel therefore opened no socket and rendered nothing, and `tests/test_vscode_extension.py` stayed green because it grepped the source text instead of the document. That suite now cooks the literal the way the host does and requires the result to equal what Node makes of the same file, and `tests/test_site_app_parity.py` hands every script the shipped sheets reference — the popup's module graph, the landing's eight files, the gateway page's inline block, 12 in all — to a JS engine with the type its own tag declares, and refuses a `src` or an `import` that names a file which does not ship
- What a browser paints is now measured as a browser paints it, not as CSS declares it. The console's contrast sweep judged text at full strength when an ancestor faded it, so `.btn-primary:disabled { opacity: .55 }` was reported as a 1.76:1 failure on `/settings` while the composited colour nobody could read was 3.2:1 away from the real number; and an SVG chart label was judged by the CSS `color` it inherits instead of the `fill` it paints, which is the seam recharts uses to move an axis' `stroke` onto its tick text. The survey now folds every ancestor's `opacity` into the ink before the ratio, reads a painted fill for SVG text, and exempts exactly the state WCAG 1.4.3 exempts — a `disabled` control, not an `aria-disabled` one, which the fold proves still fails. Five probes at known ratios hold the fold, and both directions are proved against planted violations: a detector that stopped folding, and one that folded everything into an exemption
- The full gate stopped failing the Postgres suite on a machine that has no Postgres. `check_all.py` types `tests/integration/`, and the conftest reads a typed path as a request to prove it — the doctrine the last wave bought deliberately, because a field of skips had reported green while the gateway could not write a session row at all — so every box without a server, CI's own main job included, got `17 ERRORS -- 5 passed`. Whether a server answers is a fact about the machine, so the gate now asks the machine before it nominates the directory: one connection, resolved the way the fixture resolves it. Where nothing answers, the `postgres` cases are deselected — and the marker is applied from the `pg_dsn` fixture each case binds, not from a list of files — while the stage prints how many it left unproven and fails outright if the deselection finds none, so the marker cannot rot into a green stage over an unrun suite. `postgres-integration` in CI is untouched: with a server it still runs all 17 and still refuses to pass on nothing
- The sweep that asks whether the extension popup ships every file its documents name was reading a fragment as a file. The grain filter is inlined as `url("data:image/svg+xml,…")`, and inside those quotes sits `filter='url(%23n)'`, so a value class that stops at the first `)` accused the popup of asking for `%23n` — a request no browser makes, because the bytes come with the stylesheet. Quoted values are now matched whole, and the proof renames a real font ask in the same file to show the bare form is still read
- The status surfaces reported a version the running product never had: `/api/status` and `/api/admin/system/status` answered `"1.0.0"` and `/aios/health` `"0.1.0"` while `pyproject.toml` — the file `raven.core.version` reads — ships `0.4.8`, so an operator reading their own console saw a build that does not exist. All three answer `raven.core.version.__version__` now, and `tests/test_version_consistency.py` both asks each of them over HTTP at runtime and pins each answer site to the version module, so the next surface that hard-codes a number dies there rather than in a support reply. `/api/admin/system/status` had a second lie underneath the first: it read `gateway._running if hasattr(gateway, "_running") else False`, a fallback that answers "stopped" for any gateway that moves its own attribute, so a running gateway could be reported halted by a refactor that changed nothing about serving. `Gateway.is_running` is the published surface, nothing outside the class touches `_running`, and the test flips the state to prove the answer follows it instead of proving the key is present
- The console lost itself to a limit meant for programmatic callers: one cold navigation is 15 requests and 10 of them are files already on disk, so two reloads spent the per-IP budget of 60 and the third answered the *application shell* with `429` and raw JSON. Static bundle responses are exempted by a declaration the handler makes about itself (`raven.core.spa.BUNDLE_SERVED_ATTR`) rather than a list of paths the middleware consults, the `429` carries `Retry-After` as well as the body field `curl` and browsers cannot see, and the SPA client waits it out instead of painting an error
- A shipped install served the brand woff2 files, the service worker, the manifest, the offline shell and the icons as 37 bytes of HTML with `content-type: text/html`, because `mount_spa` mounted `/assets` and let a catch-all return `index.html` for everything else — so the console rendered in `system-ui` in production while looking correct under `vite dev`, which serves `public/` itself, and no browser test caught it because `getComputedStyle().fontFamily` reports the declared stack whether or not the file behind it ever arrived. The gateway answers for its own public files now, `favicon.ico` is served as the registered `image/vnd.microsoft.icon` instead of `application/octet-stream`, and every icon the pages, the manifest and the service worker name is a path these tests require to be a real file of the right type — the SPA shell's tab used to be filled from a `data:` URI holding a chick emoji, the one icon slot a document can paint without the gateway ever being asked for a byte
- The pre-hydration boot script picked a theme the app then contradicted: it read a different key than `getInitialTheme` reads and left `theme-color` at the dark value, so an operator running the light theme got a dark browser chrome, a dark first paint, and a flip after hydration. It validates the stored value against the same three themes and the same `prefers-color-scheme` fallback as the app, and writes the `theme-color` of the theme it chose
- A metric's Prometheus label schema was decided by whichever caller arrived first, and every other shape raised from inside the metric call. Measured: an unlabelled `metrics.observe("llm_request", …)` built the histogram with no label names, so the gateway's own next request — which `raven/core/instrumented.py:28` always records under its provider and model — died with `ValueError: No label names were set when constructing histogram:raven_llm_request_duration_seconds`; reverse the order and the same seam raises `counter metric is missing label values`. A metric call sits on the request path, so calls are now projected onto the schema the name already carries: a dimension it cannot hold counts under the empty label and is said out loud once. The same collector's text surface spelled labels *inside* the metric name — `raven_messages_received{channel=webchat}_total 1` — which the exposition grammar does not accept, so `prometheus_client`'s parser raises on it and `/api/metrics/prometheus` answered a scrape with an error while `/api/metrics` reported those same numbers as JSON; it emits one `# TYPE` per family, labels after the full name, values quoted and escaped, and `tests/core/test_metrics_label_schema.py` judges it with the parser a scraper runs rather than with a regex of this repo's own. `scripts/gen_api_fixtures.py` had been warming these metrics without the labels the gateway passes, so the emitted payload spelled keys no running gateway answers
- `/api/admin/channels` and `/api/admin/channels/{name}` disagreed about whether a channel was up, because the list read `dict` membership off what is a `ChannelManager` and the detail asked the channel itself. Both ask `health_check()` now, and `tests/core/test_admin_channel_surface.py` requires the two answers to agree for every registered channel — a readiness claim that differs between the list and the detail is the operator's bug report, not a test fixture

### Security
- Both `/mcp` routers refuse a denied tool on `POST /mcp/tools/{name}` as they already did on `/mcp/rpc`. A gate discovers every router module by scanning the tree, so a third one cannot stay permissive by being forgotten
- `GET /mcp/events` requires authorization
- A verification credential is spent once, and an unenforceable CORS policy is refused
- Tool errors stay out of responses
- Extension popup links accept only absolute http(s); `qs` 6.17.1, Pillow and libpcre2 raised to releases that close their advisories
- A chat transcript exported into the working tree is no longer tracked, and root Markdown is opt-in in `.gitignore`, so a renamed export cannot reach a public commit again

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

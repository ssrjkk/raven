---
description: "DM pairing policy, tool execution levels, workspace confinement, context visibility and PII redaction, and sandboxing."
---

# Security Overview

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven runs as a single-process monolith that talks to messaging channels, an LLM
provider, a web dashboard and a filesystem workspace. The controls below are
layered so that a failure in one layer does not expose the others, and the
authentication layers **fail closed** — an unconfigured secret rejects traffic
instead of accepting it.

| # | Layer | Enforces | Code |
|---|-------|----------|------|
| 1 | DM access policy | Who may talk to the bot | `raven/core/config.py`, `raven/core/gateway/gateway.py` |
| 2 | Tool execution policy | Which tools may run, and whether the user must confirm | `raven/core/security/tool_policy.py` |
| 3 | Workspace isolation | File access stays inside the workspace, symlinks included | `raven/core/security/path_guard.py` |
| 4 | Context visibility + PII redaction | What external content and secrets reach the model | `raven/core/security/context_filter.py` |
| 5 | Sandboxing | Resource and network caps for executed code | `raven/core/security/sandbox_policy.py`, `code_sandbox.py` |
| 6 | HTTP authentication + RBAC | Who may call which API route, and with which role | `raven/core/middleware.py`, `raven/core/auth/rbac.py`, `tokens.py` |
| 7 | Rate limiting | Per-IP HTTP limits and per-channel/per-user token buckets | `raven/core/middleware.py`, `raven/core/security/rate_limiter.py` |
| 8 | Input sanitization + response headers | Malformed bodies are refused; responses carry hardening headers | `raven/core/middleware.py` |
| 9 | Webhook authentication | Unsigned callbacks never reach an action | `raven/core/webhooks.py` |
| 10 | SSRF guard | Outbound fetches cannot reach internal addresses | `raven/core/security/ssrf.py` |
| 11 | Credentials at rest | Key derivation, secret masking, signed audit trail | `raven/core/auth/password.py`, `raven/core/config.py`, `raven/core/audit.py` |
| 12 | Untrusted XML | `defusedxml` only, never `xml.etree` | `raven/tools/tests.py`, `raven/coding/test_generator.py` |
| 13 | Self-audit + CI scans | Configuration and dependencies are checked continuously | `raven/core/security/security_audit.py`, `.github/workflows/` |
| 14 | Egress map | Every host the code can reach is declared, and an undeclared one fails the build | [egress.md](egress.md), `tests/test_egress_map.py` |

## 1. DM Access Policy

`dm_policy` (default `pairing`) is validated at startup and accepts only:

- **pairing** — unknown senders get a pairing code and are ignored until approved
- **open** — all messages processed (requires an allowlist)
- **closed** — only explicitly allowed senders

An invalid value is a startup error, not a silent fallback (`Settings.model_post_init`).

## 2. Tool Execution Policy

`raven/core/security/tool_policy.py` combines three mechanisms:

- **exec security level** (`exec_security`, default `deny`) — applies to the *exec class* of
  tools, one shared list (`EXEC_CLASS_TOKENS`: shell, python, `process_*`, `browser_*`, `mcp_*`,
  `*_exec`, `*trigger*`, `ci_run_workflow`, `ci_jenkins_job`, `run_code`, `http_put`,
  `http_delete`, `chaos_*`, `db_query`, `http_post`, `email_send`, the git mutating verbs and
  `plugin_*`). `deny` refuses them, `ask` routes them through confirmation, `full` permits
  everything. Matching is separator-insensitive, so a namespaced plugin tool and the registry name
  of the same capability are one tool to the gate — matching the raw string let the gated one be
  walked around by calling the dotted twin. `Agent._execute_tool()` consults it for
  every exec-class call, `create_task_tool_registry()` strips exactly this set from
  planner-driven tasks, and with `deny` the offer drops these names too — a tool the model is
  handed and then reads a refusal from is a wasted turn, not a choice
- **exec ask mode** (`exec_ask_mode`, default `always`) — only read when the level is
  `ask`: `always` confirms every exec, `on-miss` confirms tools that are not already in
  the profile or allowlist, `off` skips confirmation. **A confirmation that cannot be asked is a
  denial, not a pass**: with no `confirm_fn` wired the call is refused with the reason, the CLI
  agents ask on the controlling terminal and deny when there is no terminal
  (`raven/core/security/confirm.py`), and a channel that has not implemented
  `ask_confirmation()` — thirteen of the fifteen adapters, including webchat — denies instead of
  answering for the user
- **tool profiles** (`messaging` / `minimal` / `full`) — an allow-list over the plugin
  tools on the agent path. `messaging` allows exactly `files.read`, `api.http_get`,
  `memory.recall` and `browser.search`: it can read a file in the workspace and cannot write one.
  `browser.search` is exec-class, so with the shipped `EXEC_SECURITY=deny` the offer drops it and
  the messaging deployment keeps three tools; raising the level to `ask` or `full` is the operator
  decision that gives search back. `minimal` and the `full` profile contain no exec-class tool.
  `full` ignores the list
- **the tool ruleset** (`policy/tools.json`) — the file-shaped gate the two lists above are
  enforced through. `ToolPolicyEvaluator` asks `PolicyEngine` on every tool call and every exec
  check, so a tool the file denies is refused even with an empty `TOOLS_DENY` and `profile=full`,
  and refused before the operator is asked to confirm — the prompt never offers what the file has
  already ruled out. It is a veto and nothing more: a `deny` tightens what the switches
  above decided, an `allow` never widens it, so `EXEC_SECURITY=full` stays meaningful with the file
  in place. The shipped rules refuse `api.http_post`, `sessions.sessions_spawn`, `process.kill`,
  `process.run`, `process.run_python`, `git.git_push`, `git.git_pull` and any tool of the
  `automation` group

`policy/` is looked for next to the source tree and, for an installed wheel, inside the package at
`raven/policy/`; `RAVEN_POLICY_DIR` names another directory. The first tool decision of the process
reads the file and a running gateway keeps that copy, so an edit needs a restart.

A ruleset that is absent enforces nothing, and the gateway says so once per name:
`Policy ruleset 'tools' not found under …` names the directory it looked in. A ruleset that is
present but cannot be read or parsed refuses every tool call until it can be read again — a policy
the program cannot open is not a policy that permits everything.

Arguments that name a filesystem location (key in `PATH_ARG_KEYS`, or suffixed `_path`, `_file`,
`_dir`, `_root`, `_cwd`) are additionally resolved against the workspace root, and paths deeper
than `MAX_PATH_DEPTH` (20) segments are rejected. A `command`, `url` or `sql` string is not a
location and is not resolved as one — restraining those is the exec level's job.

On the task and orchestrator path, authorization is per subject: `ToolSpec.dangerous` and
`ToolSpec.allowed_roles` (with `tool_policy.json` overrides, `raven/core/tools_rbac.py`) are
enforced by `ToolRegistry.call(..., role=…)`. A call that carries no role runs only the tools
with no role restriction, and the role a task runs under is written by whoever created it, never
by the planner.

## 3. Workspace Isolation

One directory is the boundary. `raven/core/workspace.py:workspace_root` decides it per call:
the root the process pinned (`--workspace` on an MCP server, gateway startup), then
`RAVEN_WORKSPACE`, then `WORKSPACE_PATH`, then the working directory. `raven doctor` prints the
result and who decided it.

`workspace_only` defaults to `True`, and every surface that confines a path takes its base from
that one root:

- `raven/core/security/path_guard.py:confine_path(path, base)` — the registry file tools, the
  debugger, the git console and the `/code` command. It calls `os.path.realpath` on **both** the
  base and the target before comparing, so a symlink planted inside the workspace that points out
  (`/workspace/link -> C:\Users\...`) is rejected: the check runs on the resolved location, not the
  lexical one.
- `raven/core/workspace.py:confine` — the plugin tools (`files`, `ocr`, `git`). Workspace plus the
  system temp directory, and a refusal names both.
- `ravencode/runtime/workspace.py:confine` — the coding agent's own tools: workspace only, no temp
  directory, deliberately the strictest of the three.

Where a tool names a directory, that directory is confined before the process starts:
`raven/tools/tests.py:run_tests` and `test_coverage` collect from the workspace root rather than
wherever the gateway happened to launch, and `raven/plugins/git/plugin.py:_run_git`, the coding
agent's git tools and `ravencode/runtime/autogit.py` run `git` inside the confined root. A tool with
no directory argument (`raven/tools/shell.py`) inherits the process's own working directory.
`WORKSPACE_ONLY=false` switches the policy-layer check off, which `raven doctor` reports as a
warning; it does not change the tools' own confinement above.

## 4. Context Visibility and PII Redaction

`context_visibility` defaults to `allowlist` (`all` / `allowlist` / `allowlist_quote`), so
quoted or fetched content from unknown sources is filtered before it reaches a prompt.
`context_filter.py` also redacts PII (`redact_pii`) and credential-shaped strings, which
protects both the outbound prompt and the stored transcript.

## 5. Sandboxing

`sandbox_mode` (default `non-main`) decides **which sessions** run sandboxed; the
`SandboxPolicy` objects in `raven/core/security/sandbox_policy.py` decide **how**, and are
selected per session class (`session_type_to_policy` maps `main` / `code` / `web` / `plan`
to the policies below). Each policy carries its own tool allow/deny lists, network flag and
resource caps:

| Policy | Tools | Network | Memory | Timeout | Backend |
|--------|-------|---------|--------|---------|---------|
| `main` | all | yes | 512 MB | 60 s | `subprocess` |
| `non-main` | 9 allowlisted | **no** | 128 MB | 15 s | `docker` (`python:3.12-slim`) |
| `code-exec` | `read`, `write`, `bash`, `process` | allowlisted only | 256 MB | 30 s | `docker` |
| `web-browsing` | browser + `web_fetch`/`web_search` | yes | 512 MB | 60 s | `none` |
| `read-only` | `read`, `glob`, `grep`, `web_search`, `web_fetch` | yes | 256 MB | 30 s | `none` |

`get_policy()` falls back to `non-main` for an unknown name, so a typo in configuration
narrows privileges instead of widening them. The two interactive policies run without a
container backend (`sandbox_mode="none"`) and are constrained by their tool allowlist
instead — `read-only` and `web-browsing` deny `bash`, `write` and `edit` outright.

`code-exec` is the only policy that carries `network_rules`:
`{"allow": ["pypi.org", "github.com", "files.pythonhosted.org"], "deny": ["*"]}` —
network is reachable, but only for dependency and source hosts.
All policies share `max_cpu_percent=50` and `max_pids=64` caps. `code_sandbox.py`
performs the platform capability detection that decides whether the docker backend is
actually available.

## 6. HTTP Authentication and RBAC

`auth_middleware` (`raven/core/middleware.py`) resolves a caller before any route runs, then
applies four escalating rules:

- **identity** — a `Bearer` token, an `X-Raven-Key` header, or a `?token=` query parameter
  (WebSocket and SSE clients cannot set headers). Session tokens are validated by
  `token_manager`; a raw `WEB_SECRET_KEY` match grants `admin` and is compared with
  `hmac.compare_digest`, never `==`. Gateway logs record `request.url.path` without the query
  string, so a token passed that way is not written to the access log
- **always-authenticated prefixes** — `/aios`, `/api/tests` and `/mcp` reject anonymous callers
- **RBAC** — `PATH_PERMISSIONS` maps 19 route prefixes (`/api/admin`, `/api/secrets`,
  `/api/auth/users`, `/aios/exec`, …) to a required `Permission`, checked against the caller's
  role, so a `user`-role token gets `403` on admin surfaces even when authenticated
- **fail-closed writes** — any `POST`/`PUT`/`PATCH`/`DELETE` under `/api` from an anonymous
  caller is `401`. The only exemptions are `/api/auth/*` (login itself) and `/api/webhooks/*`,
  which authenticate by signature instead (section 9)

**Secure mode** is what separates a local bench run from a deployed one: as soon as a
`WEB_SECRET_KEY` is configured, the 27 read prefixes in `_PRIVATE_READ_PREFIXES`
(chat search, e-mail inbox/config, insights, RAG, voice biometrics, analytics, knowledge
graph, CI/CD, monitors, tasks, `/api/status`, `/api/metrics`, agent and tool-policy
introspection, the canvas proxy) also require authentication. Without a secret they stay
readable so the dashboard works offline. Six paths are public in both modes:
`/aios/health`, `/aios/metrics`, `/docs`, `/docs/oauth2-redirect`, `/openapi.json`, `/redoc`.

## 7. Rate Limiting

Two independent mechanisms, because they protect different surfaces:

- **HTTP middleware** — 60 requests / 60 s per IP (`rate_limit_max`, `rate_limit_window`);
  exceeding `1.5x` the limit blocks the IP temporarily, and a block auto-releases after
  twice the window. Counters are pruned so the table cannot grow without bound.
- **Channel/user token buckets** — per-transport budgets (Telegram 3/s burst 6, Discord
  5/s burst 10, Slack 8/s burst 16, WebChat 10/s burst 20) plus per-user-category limits,
  both overridable at runtime via `set_channel_limit` / `set_user_limit`.

## 8. Input Sanitization and Response Headers

Request bodies are parsed defensively in `raven/core/middleware.py`: `POST`/`PUT`/`PATCH`
JSON bodies are decoded before the handler sees them, nesting deeper than 10 levels is
refused, and invalid JSON returns `400` rather than reaching a handler.

`security_headers_middleware` adds to every response:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`,
`Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (geolocation,
microphone, camera, payment all disabled) and a `Content-Security-Policy` — `default-src
'self'`, `frame-ancestors 'none'`, `object-src 'none'`, `form-action 'self'`, with
`'unsafe-inline'` limited to scripts and styles the SPA needs and `connect-src` restricted
to same-origin plus the local gateway. CSP is applied with `setdefault`, so a route that
needs a stricter policy can set its own. `Strict-Transport-Security` is added only when the
request actually arrived over HTTPS.

## 9. Webhook Authentication — Fail Closed

Every webhook entry point verifies an HMAC before doing any work, and **refuses the
request when no secret is configured**:

- generic, Google Chat, Signal, Teams, Feishu, LINE, GitHub, GitLab, GitHub Actions and
  Allure callbacks share `_verify_webhook_signature`, which compares a `sha256=<hex>`
  HMAC-SHA256 digest of the raw body against `WEB_SECRET_KEY`
- `slack/events` prefers `SLACK_SIGNING_SECRET`, falls back to `WEB_SECRET_KEY`, and also
  enforces timestamp freshness to block replays
- WhatsApp requires a configured token

Missing secret → `403 "… not configured"`, never an implicit accept. Before this was
fixed, an unconfigured deployment executed self-heal and QA actions on unsigned input.

## 10. SSRF Guard

Every fetch whose URL a model can supply — the plugin tools — goes through
`safe_fetch_async` (`raven/core/security/ssrf.py`) instead of a bare `httpx.get`; the gate
`tests/test_plugin_surface_integrity.py::test_no_plugin_fetches_through_an_unpinned_client`
fails if a published `plugin.py` constructs an `httpx.AsyncClient` itself. Code that talks to a
configured endpoint rather than a caller-supplied address (42 `httpx.AsyncClient(` sites under
`raven/`, 5 under `ravencode/`) is not covered by that guarantee:

- scheme allowlist (`http` / `https`)
- the address that is actually connected to is checked, not only the URL: the hostname is
  resolved and every answer (literal or DNS) is tested against loopback, link-local,
  RFC 1918, CGNAT `100.64.0.0/10`, `192.0.0.0/24`, benchmarking `198.18.0.0/15`,
  `240.0.0.0/4`, `fc00::/7` and `fe80::/10`
- the connection is pinned to the validated address while `Host` and the TLS SNI stay the
  requested name (with its port), so a public name that resolves privately is blocked and
  a pinned HTTPS request still verifies the certificate of the host it asked for
- every redirect hop is re-validated **and IP-pinned**, so a public hostname that
  redirects to `127.0.0.1` / `169.254.169.254` or resolves privately on retry is blocked
- bounded redirects (5) and a streamed response capped at 10 MiB to stop memory exhaustion

## 11. Credentials at Rest

- Passwords: PBKDF2-HMAC-SHA256, **600 000 iterations**, 32-byte random salt per hash.
  Legacy 100 000-iteration hashes still verify and are rehashed on successful login.
- Login sessions are rows in `auth_sessions` keyed by `sha256(token)`, with a 24-hour expiry;
  they survive a restart, are revoked by logout/logout-all/deactivation, and a database dump
  contains no usable bearer token. Migration 12 revokes the rows stored before this change,
  because a plaintext token cannot be turned into a digest retroactively.
- The uvicorn access log is disabled: SSE and WebSocket clients can only pass their token in
  the query string (`?token=`), and the access log prints the request line verbatim.
- Configuration secrets use `SafeSecretStr`, so API keys and webhook secrets do not appear
  in `repr()`, logs or exception traces.
- The audit trail is signed with Ed25519 using a private key auto-generated as
  `audit_signing_key.bin` under the data dir, so tampering with recorded events is detectable.
  The key never leaves that file; `RAVEN_AUDIT_SIGNING_KEY` supplies it explicitly instead.

## 12. Untrusted XML

Coverage and test-generation parsing uses `defusedxml.ElementTree`, not the stdlib parser,
so entity expansion and external-entity payloads cannot be used against the agent tools
that read `coverage.xml`.

## 13. Self-Audit and CI

`security_audit.py` runs 22 configuration checks against the live deployment (sandbox mode,
workspace confinement, secrets, CORS, TLS) and returns fix hints; `--deep` adds 8 more that
touch the network or the filesystem - dependency versions through `pip-audit`, the env-file,
log and signing-key permissions, the Docker sandbox, network exposure, token expiry and the
session timeout.
The `deep` dependency check shells out to `pip-audit` with a 60 s ceiling, so a blocked
PyPI mirror reports a timeout instead of hanging the run.

On the CI side, the Security scan job installs `.[dev]`, freezes the resolved set with
`pip freeze --exclude-editable` and runs `pip-audit --strict --no-deps` against it — no
`|| true`, so a known vulnerability fails the build. Dependency floors in `pyproject.toml`
encode the versions that close published advisories (for example `cryptography>=50.0.0`),
which is what keeps that job green. The rest of the CI side adds CodeQL, dependency
review, a secrets scan (gitleaks), a Trivy image scan in the deploy workflow, and a
Windows job that runs the lint/type/import/CLI checks plus the workspace-isolation and
security test files — the platform-specific path handling is covered on the platform.
Vulnerability reporting is described in `SECURITY.md` at the repo root.

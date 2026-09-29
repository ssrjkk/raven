# Security Overview

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

## 1. DM Access Policy

`dm_policy` (default `pairing`) is validated at startup and accepts only:

- **pairing** — unknown senders get a pairing code and are ignored until approved
- **open** — all messages processed (requires an allowlist)
- **closed** — only explicitly allowed senders

An invalid value is a startup error, not a silent fallback (`Settings.model_post_init`).

## 2. Tool Execution Policy

`raven/core/security/tool_policy.py` combines three mechanisms:

- **exec security level** (`exec_security`, default `deny`) — `deny` blocks shell/exec
  tools outright, `ask` routes them through confirmation, `full` permits everything
- **exec ask mode** (`exec_ask_mode`, default `always`) — only read when the level is
  `ask`: `always` confirms every exec, `on-miss` confirms tools that are not already in
  the profile or allowlist, `off` skips confirmation
- **tool profiles** (`messaging` / `minimal` / `full`) — per-agent surface area, so a
  messaging agent cannot reach filesystem tools at all

Every string argument is additionally resolved against the workspace root
(`_resolve_safe`), and paths deeper than `MAX_PATH_DEPTH` (20) segments are rejected. The
`dangerous` flag on each tool spec is what the confirmation flow keys on; `ravencode` and
`raven` both honour it.

## 3. Workspace Isolation

`workspace_only` defaults to `True`. All path-bearing tools resolve through
`confine_path(path, base)`, which calls `os.path.realpath` on **both** the base and the
target before comparing. A symlink planted inside the workspace that points outside
(`/workspace/link -> C:\Users\...`) is therefore rejected — the check runs on the
resolved location, not the lexical one. `ravencode/runtime/tools/git_tests.py` and the
`raven` file/shell tools additionally confine any subprocess `cwd` to the workspace root.

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
- **RBAC** — `PATH_PERMISSIONS` maps 18 route prefixes (`/api/admin`, `/api/secrets`,
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

Outbound fetches go through `safe_fetch_async` (`raven/core/security/ssrf.py`) instead of
a bare `httpx.get`:

- scheme allowlist (`http` / `https`)
- every redirect hop is re-validated **and IP-pinned**, so a public hostname that
  redirects to `127.0.0.1` / `169.254.169.254` or resolves privately on retry is blocked
- bounded redirects (5) and a streamed response capped at 10 MiB to stop memory exhaustion

## 11. Credentials at Rest

- Passwords: PBKDF2-HMAC-SHA256, **600 000 iterations**, 32-byte random salt per hash.
  Legacy 100 000-iteration hashes still verify and are rehashed on successful login.
- Configuration secrets use `SafeSecretStr`, so API keys and webhook secrets do not appear
  in `repr()`, logs or exception traces.
- The audit trail is HMAC-signed with a key auto-generated at `data/audit_signing_key.bin`,
  making tampering with recorded events detectable.

## 12. Untrusted XML

Coverage and test-generation parsing uses `defusedxml.ElementTree`, not the stdlib parser,
so entity expansion and external-entity payloads cannot be used against the agent tools
that read `coverage.xml`.

## 13. Self-Audit and CI

`security_audit.py` runs 31 configuration checks against the live deployment (sandbox mode,
workspace confinement, secrets, CORS, TLS, dependency versions) and returns fix hints.
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

# Security Overview

Raven AI implements a defense-in-depth security model with multiple layers of protection.

## Layers

### 1. DM Access Policy

Controls who can send direct messages to the bot:
- **pairing** (default) — unknown senders receive a pairing code
- **open** — all messages processed (requires allowlist)
- **closed** — only explicitly allowed senders

### 2. Tool Execution Security

Controls what tools the agent can execute:
- **deny** (default) — shell/exec tools blocked by default
- **ask** — user must confirm each execution
- **full** — all tools permitted

### 3. Workspace Isolation

File access is restricted to the workspace directory by default (`workspace_only: true`).

### 4. Context Visibility

Controls what external content the agent can see:
- **all** — full context visible
- **allowlist** — only allowlisted domains
- **allowlist_quote** — allowlisted + quoted content

### 5. Sandboxing

Non-main sessions can be sandboxed:
- **subprocess** — run in isolated subprocess (default)
- **docker** — run in Docker container
- **none** — no sandboxing

### 6. Rate Limiting

- 60 requests per 60-second window per IP
- Burst multiplier: 1.5x before temporary IP block
- Blocked IPs auto-released after 2x window

### 7. Input Sanitization

- JSON body depth limited to 10 levels
- Non-string JSON keys rejected
- Invalid JSON returns 400

### 8. Audit Trail

All security-relevant events are logged:
- Authentication successes/failures
- Tool execution attempts
- Configuration changes
- Policy violations

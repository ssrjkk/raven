# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| >= 0.3  | :white_check_mark: |
| < 0.3   | :x:                |

## Reporting a Vulnerability

We take the security of Raven AI seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them via email to **security@raven.ai** (or the project maintainer's email).

You should receive a response within 48 hours. If you do not, follow up via email to ensure we received your original message.

### What to include

- Type of issue (e.g., buffer overflow, SQL injection, cross-site scripting, etc.)
- Full paths of source file(s) related to the manifestation of the issue
- The location of the affected source code (tag/branch/commit or direct URL)
- Any special configuration required to reproduce the issue
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

## Security Model

### DM Access Policy

By default, Raven uses a **pairing** policy:
- Unknown senders receive a pairing code
- The bot does not process their message until the code is approved
- Approve with: `raven pairing approve <channel> <code>`

Available policies:
- `pairing` (default) — pairing code required for new senders
- `open` — all messages processed (must also configure `allowFrom`)
- `closed` — only explicitly allowed senders

### Tool Execution Security

- **exec_security**: `deny` (default), `ask`, or `full`
- **workspace_only**: `true` (default) — restricts file access to workspace
- **sandbox_mode**: `non-main` (default) — runs non-main sessions in sandboxes
- **sandbox_backend**: `subprocess` (default), `docker`, or `none`

### Context Visibility

- `all` (default) — full context visible
- `allowlist` — only allowlisted domains visible
- `allowlist_quote` — allowlisted domains visible, quotes shown as-is

### Rate Limiting

- Default: 60 requests per 60-second window per IP
- Burst multiplier: 1.5x before IP is temporarily blocked
- Blocked IPs are released after 2x window

## Security Audit

Run `raven security audit` to perform 23 standard checks and 8 deep checks including:
- Secret key strength
- API key configuration
- File permissions
- CORS configuration
- HTTPS enforcement
- Sandbox configuration
- Session timeouts
- Docker security
- Dependency vulnerabilities

## Responsible Disclosure

We kindly ask that:
- You give us a reasonable time to fix the issue before disclosing it publicly
- You make a good faith effort to avoid privacy violations, destruction of data, and interruption of our service
- You do not exploit a security issue you discover for any reason other than testing

## Recognition

We believe in recognizing and thanking security researchers who help us keep our users safe. If you report a valid security issue, we will acknowledge your contribution in our release notes (unless you prefer to remain anonymous).

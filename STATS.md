# Raven AI — Project Statistics

## Overview

- **Language**: Python 3.13+, Go 1.26, Rust, TypeScript
- **Tests**: 859+ unit tests (pytest), Go table-driven tests, Vitest, Playwright E2E
- **Channels**: 12 messaging platforms
- **Plugins**: 10 built-in plugins
- **Services**: 6 microservices + gateway + daemon
- **Lines of code**: ~150,000+

## Codebase Distribution

| Directory | Language | Purpose |
|-----------|----------|---------|
| `raven/` | Python | Core engine, channels, CLI, tools |
| `ravencode/` | Python | High-level AI agent API |
| `services/` | Go, Python | Microservices (gateway, auth, monitor, RAG, task, code) |
| `web/` | TypeScript | React 19 dashboard |
| `desktop-tauri/` | Rust, TypeScript | Tauri desktop shell |
| `daemon/` | Rust | System daemon (ravend) |
| `plugins/` | Python | User-extensible plugins |
| `deploy/` | YAML, Docker | Infrastructure as code |

## CI/CD

- GitHub Actions: 9 workflows
- Docker: Multi-stage, distroless, non-root
- Code coverage tracked via Codecov

## Security

- 30+ mypy bugs fixed in May 2026 security audit
- Full security audit CLI: `raven security audit --deep --fix`
- SSRF, SQL injection, XSS, path traversal guards in place

# Raven AI — Project Statistics

## Overview

- **Language**: Python 3.11+ (tested on 3.12), TypeScript
- **Tests**: 4,677+ pytest tests, Vitest frontend tests
- **Channels**: 15 messaging platforms
- **Plugins**: 10 built-in plugins + user-defined plugins
- **Codebase**: single Python monolith + React SPA
- **LLM providers**: 10 (OpenAI, Anthropic, OpenRouter, Ollama, vLLM, Azure, Groq, Bedrock, Vertex AI, Copilot)

## Codebase Distribution

| Directory | Language | Purpose |
|-----------|----------|---------|
| `raven/` | Python | Core engine, 15 channels, CLI, 30+ tools |
| `ravencode/` | Python | Autonomous coding agent (50+ tools) |
| `aios/` | Python | Thin FastAPI AI-Gateway bridge |
| `web/` | TypeScript | React 19 + Vite dashboard |
| `plugins/` | Python | Built-in plugin packages (inside `raven/plugins/`) |
| `deploy/` | YAML, Docker | Docker, systemd, observability, traefik configs |
| `scripts/` | Python, PS1 | Build/launch tooling (incl. `check_all.py` gate) |

## CI/CD

- GitHub Actions: 15 workflows (lint, typecheck, tests, e2e, deploy, release, security scans)
- Docker: multi-stage builds
- Validation gate: `python scripts/check_all.py` (ruff + mypy + imports + all tests + frontend build, 12 checks)

## Security

- 0 mypy errors, 0 ruff violations project-wide
- Full security audit CLI: `raven security audit --deep`
- SSRF, SQL injection, XSS, path traversal guards in place and covered by tests
- Pressure-tested: full suite 4,677 passed in ~5 min
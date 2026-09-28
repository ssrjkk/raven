# Raven AI — Project Statistics

## Overview

- **Language**: Python 3.11+ (tested on 3.12), TypeScript
- **Tests**: 5,139 pytest tests (27 skipped), 89 Vitest frontend tests
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
| `extension/` | JS, TS | Chrome MV3 side-panel extension + VS Code extension |
| `scripts/` | Python, PS1 | Build/launch tooling (incl. `check_all.py` gate, icon generators) |

## CI/CD

- GitHub Actions: 10 workflows (lint, typecheck, tests, e2e, extension, deploy, release, EXE build, security scans)
- Docker: multi-stage build (Python wheel + React SPA built in-image)
- Validation gate: `python scripts/check_all.py` (ruff + mypy + imports + all tests + frontend build, 12 checks)

## Security

- 0 mypy errors, 0 ruff violations project-wide
- Full security audit CLI: `raven security audit --deep`
- SSRF, SQL injection, XSS, path traversal guards in place and covered by tests
- Pressure-tested: full suite 5,139 passed, 27 skipped (local Windows run ~13 min, CI ~6 min)
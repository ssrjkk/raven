<div align="center">

# Raven

**by [@ssrjkk](https://github.com/ssrjkk)**

A self-hosted AI assistant that lives on your own server: a persistent gateway with 15 messaging
channels, an autonomous coding agent, and a web dashboard — in one Python process.

[English](README.md) · [Русский](README.ru.md)

[![CI](https://img.shields.io/github/actions/workflow/status/ssrjkk/raven/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ssrjkk/raven/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-5%2C100%2B-brightgreen)](https://github.com/ssrjkk/raven/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![CodeQL](https://img.shields.io/badge/code%20scanning-0%20alerts-success?logo=github)](https://github.com/ssrjkk/raven/security/code-scanning)

</div>

---

## What it is

Raven is two programs that share one codebase:

- **RavenCode** — an autonomous coding agent that reads and edits your project: streaming ReAct loop, 66 tools (files, bash, git, web, tests, memory), LSP auto-enrichment for Python/TypeScript/Go/Rust, parallel sub-sessions, plan/safe/fast modes, checkpoints and undo.
- **RavenFlow** — a persistent gateway daemon that connects the agent to messengers, routes messages to agents, streams answers over WebSocket, and runs scheduled routines and passive monitors (HTTP, prices, RSS, files, processes).

Both are driven by the same gateway: 15 messaging channels, a task planner, a RAG memory store (embeddings + BM25, local-first), voice input/output, and a React web dashboard with a Monaco IDE.

## Requirements

- Python 3.11+ and at least one LLM API key (or a local Ollama/vLLM server)
- Node.js 22+ only if you want to rebuild the web dashboard from source
- Docker optional — the whole system runs as a single process

## Quick start

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven
pip install -e .

cp .env.example .env        # add at least one LLM API key
raven onboard               # interactive setup wizard
raven start                 # gateway + web UI on http://localhost:18888
```

The three entry points:

| Command | What it runs |
|---|---|
| `raven start` | The gateway: channels, web dashboard on port 18888 |
| `ravencode tui` | The coding agent in a terminal session |
| `ravenflow` | The workflow daemon on port 18789 |
| `raven-mcp` | MCP server (stdio) for Claude Desktop, Qoder, opencode, Cursor |

Or with Docker:

```bash
docker compose up -d
```

## What it can do

**Talk** — Telegram (with inline buttons and voice messages), Discord, Slack, WhatsApp, Matrix,
Teams, Signal, IRC, LINE, Feishu, Google Chat, GitHub, GitLab, email, and a built-in web chat.
Direct messages are gated by a pairing code; group behaviour is configurable per channel.

**Code** — the agent reads your repository, enriches context through language servers
(pyright, tsserver, gopls, rust-analyzer), edits files, runs tests, commits. Sessions are
check-pointed and reversible with `undo_changes`. Plan mode shows what it would do without
writing anything.

**Remember** — conversation memory plus a document knowledge base: chunking for PDF/text/code,
embeddings (OpenAI or local) and BM25 keyword search, all stored locally.

**Run on a schedule** — routines (morning briefings, inbox checks) and monitors that watch a
URL, a price, an RSS feed, a file or a process and alert you when a condition trips.

**Fail over** — ten LLM providers (OpenAI, Anthropic, OpenRouter, Ollama, vLLM, Azure, Groq,
Bedrock, Vertex AI, Copilot) behind one router with circuit breakers and rate-limit backoff.
If a model starts failing, the next one takes over mid-conversation.

**Stay safe** — JWT auth with roles, per-tool allow/deny policy, five sandbox profiles for code
execution, workspace isolation with symlink protection, SSRF guard on every outbound request,
Fernet-encrypted secrets, audit log. See [docs/security/overview.md](docs/security/overview.md).

## CLI cheat sheet

```bash
raven start / stop / status    # manage the gateway
raven doctor                   # diagnostics
raven tui                      # terminal dashboard
raven agent --message "..."    # one-shot question
raven code start --goal "..." --project ./my-project
raven code review <file>       # AI code review
raven task run "<goal>"        # multi-step task
raven monitor add ...          # watch a URL / price / feed / file / process
raven routine add ...          # schedule a routine
raven security audit --deep    # audit env, network, dependencies
raven db backup                # backup the database
raven models list              # configured LLM providers
```

The full command reference is in the CLI itself: `raven --help`, and `<command> --help` for any group.

## Configuration

Everything is configured through environment variables (`.env` is read from the project
directory, `~/.raven/.env`, or the install root). The essentials:

```bash
# LLM — at least one provider
OPENAI_API_KEY=sk-...
# or a local server:
OLLAMA_BASE_URL=http://localhost:11434

DEFAULT_MODEL=openrouter/openai/gpt-4o

# Web UI
WEB_PORT=18888
WEB_SECRET_KEY=<openssl rand -hex 32>

# Safety rails
TOOLS_PROFILE=messaging    # messaging | minimal | full — which tools are enabled
EXEC_SECURITY=deny         # deny | ask | full — shell command policy
DM_POLICY=pairing          # pairing | closed | open
SANDBOX_MODE=non-main      # main | non-main | all | none

# Optional PostgreSQL instead of SQLite
DATABASE_URL=postgresql://user:pass@localhost:5432/raven
```

The complete list with descriptions is in [.env.example](.env.example).

## Architecture

```
Channels (15)                Telegram │ Discord │ Slack │ … │ Web chat
                                  │
Gateway (FastAPI)             auth → rate limit → circuit breaker → agent routing
                                  │
        ┌─────────────────┬──────┴────────┬──────────────────┐
   RavenCode agent   Task planner    Routines & monitors   RAG memory
        │                 │               │                  │
   Tool registry (66) — files, bash, git, web, DB, canvas, cron
        │
   SQLite / PostgreSQL          LLM router → Ollama, OpenRouter, OpenAI, Anthropic, …
```

One process serves everything. Optional `docker-compose` files bring up PostgreSQL, NATS or a
Prometheus/Grafana stack next to it — see [docker-compose.postgres.yml](docker-compose.postgres.yml)
and [docker-compose.monitoring.yml](docker-compose.monitoring.yml).

## Project layout

```
raven/        gateway: channels, CLI, security, task engine, monitors, RAG, routines
ravencode/    coding agent: ReAct loop, LSP, sessions, 66 tools
aios/         FastAPI bridge for the web IDE
web/          React 19 + Vite dashboard (SPA)
extension/    browser extension (MV3) + VS Code extension
docs/         developer docs (architecture, security, channels)
tests/        pytest suite (unit, integration, e2e)
```

## Use it from your editor

Raven is also an MCP server — Claude Desktop, Qoder, opencode, Cursor, Windsurf and any other
MCP client can call its 66 tools directly:

```json
{
  "mcpServers": {
    "raven": {
      "command": "raven-mcp",
      "args": ["--workspace", "/path/to/your/project"]
    }
  }
}
```

Ready-to-paste configs for each client, the HTTP transport, and the workspace-isolation rules
are in [docs/mcp.md](docs/mcp.md).

## Development

```bash
pip install -e ".[dev]"
cd web && npm install && cd ..

python scripts/check_all.py          # ruff + mypy + imports + full test suite
python scripts/check_all.py --quick  # lint + types + imports only
```

CI runs the same gate on every push: Linux (Python 3.11 and 3.12), Windows, frontend build,
Postgres integration, E2E, dependency review, secret scan, CodeQL, and a Docker build that
imports the published image.

## Deployment

```bash
# Docker
docker compose up -d

# systemd
sudo cp deploy/raven.service /etc/systemd/system/
sudo systemctl enable --now raven

# macOS
cp deploy/com.raven.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.raven.plist
```

## Troubleshooting

```bash
raven doctor          # checks config, DB, providers, channels
tail -f data/raven.log
```

- **Port 18888 busy** — set `WEB_PORT=18889` in `.env`.
- **LLM errors** — `raven models list` shows what is configured; check keys and quotas.
- **Database** — verify `DATABASE_URL`; PostgreSQL container: `docker compose -f docker-compose.postgres.yml up -d`.

## Documentation

- [Usage guide](docs/concepts/architecture.md)
- [Русская версия](README.ru.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [License](LICENSE)

## Contact

- **GitHub:** https://github.com/ssrjkk/raven
- **Issues:** https://github.com/ssrjkk/raven/issues

## License

MIT — see [LICENSE](LICENSE).

                    .-.
                   (o o)
                   | O |
                   \___/
                  /     \
                 /       \
                /         \
               |  RAVEN   |
               |    AI    |
               |_________|
                  |   |
                  |   |
                 /     \
                /       \
               (_________)

# 🐦 Raven AI

**Personal AI Assistant — 24/7, Multi-Channel, Multi-Provider LLM**

Raven is a personal AI assistant that runs as a daemon 24/7, connecting to all your messaging platforms. Think OpenClaw, but Python-first, with built-in vector memory, native OpenRouter support, and a web UI out of the box.

---

## Features

| Feature | Raven AI | OpenClaw |
|---------|-----------|----------|
| Language | Python 3.12+ | TypeScript/Node.js |
| Architecture | asyncio monorepo | Node.js monorepo |
| Memory | Built-in (ChromaDB) | Plugin only |
| Web UI | Built-in (FastAPI + Alpine.js) | Plugin only |
| OpenRouter | Native (all models, no config) | Via plugin |
| Plugin System | 1 file = 1 plugin | Markdown + code |
| RAM Usage | ~150MB baseline | ~400MB baseline |
| Multi-Agent | Per-channel agents | Per-channel agents |
| Voice | Roadmap v2 | Built-in |

## Quickstart

### 1. Install

```bash
pip install raven-ai
```

Or from source:

```bash
git clone https://github.com/raven-ai/raven.git
cd raven
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
raven onboard    # Interactive setup
```

### 3. Run

```bash
raven start
```

Open **http://localhost:18888** for the web UI.

### Or with Docker

```bash
docker-compose -f deploy/docker-compose.yml up
```

---

## Channels

| Channel | Status | Library |
|---------|--------|---------|
| WebChat | ✅ Built-in | FastAPI WebSocket |
| Telegram | ✅ Built-in | python-telegram-bot |
| Discord | ✅ Built-in | discord.py |
| Slack | 📦 Optional | slack-sdk |
| Matrix | 📦 Optional | matrix-nio |
| WhatsApp | 🚧 Roadmap | whatsapp-web.js |
| Signal | 🚧 Roadmap | signal-cli |
| iMessage | 🚧 Roadmap | pyobjc |

## Models

All models via a unified interface:

```
openrouter/anthropic/claude-3-opus   # Best reasoning
openrouter/anthropic/claude-3-haiku  # Fast & cheap
openrouter/openai/gpt-4o             # GPT-4 Omni
openrouter/meta-llama/llama-3-70b    # Open source
claude-3-haiku-20240307              # Direct Anthropic
ollama/llama3                        # Local (Ollama)
```

Set `DEFAULT_MODEL` in `.env` or use `openrouter/` prefix for any model.

## Plugins

Built-in plugins:

- **memory** — Vector database (ChromaDB) for long-term recall
- **browser** — Web browsing, screenshots, DDG search via Playwright
- **cron** — Scheduled tasks via cron expressions
- **code** — Safe Python execution in sandbox
- **files** — File reading and manipulation

### Writing a plugin

Create a single file:

```python
# plugins/myplugin/plugin.py
PLUGIN_NAME = "myplugin"
PLUGIN_DESCRIPTION = "Does something cool"

async def my_tool(param1: str, param2: int = 42) -> str:
    """Tool description. Args: param1 (str): First param, param2 (int): Second param"""
    return f"Result: {param1} = {param2}"
```

That's it. Type hints → JSON Schema automatically.

## CLI

```bash
raven start              # Launch the gateway
raven start --port 9090  # Custom web port
raven stop               # Stop daemon
raven status             # System status
raven doctor             # Diagnostics
raven onboard            # Setup wizard
raven pairing list       # Pending pairings
raven pairing approve CODE  # Approve user
raven models list        # Available models
raven plugins list       # Loaded plugins
raven history SESSION_ID # View messages
```

## Security

- **DM Policy**: `pairing` (default), `open`, or `closed`
- **Pairing**: Users send `/pair CODE` to authorize
- **Allowlist**: Set `ALLOWED_USERS=telegram:123,discord:456`
- **Sandbox**: Code execution is isolated (no network, temp dir, timeout)

## Configuration

All config via `.env` file or environment variables. See `.env.example`.

Data stored in `~/.raven/`:
- `raven.db` — SQLite (sessions, messages, users)
- `chroma/` — Vector database for memories
- `raven.log` — Log file

## Architecture

```
raven-ai/
├── core/           # Event bus, agent loop, LLM router
├── channels/       # Messaging adapters
├── plugins/        # Plugin system + built-ins
├── web/            # Web UI
├── cli/            # Command line interface
└── deploy/         # Docker, systemd, launchd
```

## Roadmap

### v0.2 — Voice & Mobile
- Wake word detection (Porcupine)
- Text-to-Speech (ElevenLabs)
- WhatsApp via baileys bridge
- Signal via signal-cli

### v0.3 — Advanced
- Canvas (visual workspace)
- Multi-agent orchestration
- Image generation (DALL-E, Stable Diffusion)
- RAG over user documents

### v0.4 — Enterprise
- Kubernetes helm chart
- PostgreSQL support
- Team collaboration
- Audit logging

## Why Raven?

1. **Python-first** — Easier AI/ML integration, larger developer ecosystem
2. **Built-in memory** — Vector DB included, not a bolt-on plugin
3. **Native OpenRouter** — All models through one API, zero config
4. **Web UI included** — Not just messenger bots
5. **Simple plugins** — One Python file = one plugin
6. **Lower cost** — ~150MB RAM vs Node.js 400MB+

## License

MIT

---

<p align="center">
  <b>🐦 Raven AI</b> — Your personal AI, always connected.
</p>

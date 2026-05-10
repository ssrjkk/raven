<div align="center">

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="120" height="120">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#7c3aed"/>
      <stop offset="100%" stop-color="#2563eb"/>
    </linearGradient>
  </defs>
  <!-- Raven body -->
  <path d="M100 25 C85 25 70 35 60 50 L45 45 L55 60 C45 75 40 95 40 115 C40 140 50 160 65 170 L55 185 L75 172 C85 178 95 180 100 180 C105 180 115 178 125 172 L145 185 L135 170 C150 160 160 140 160 115 C160 95 155 75 145 60 L155 45 L140 50 C130 35 115 25 100 25Z" fill="url(#g)" opacity="0.95"/>
  <!-- Raven beak -->
  <path d="M60 50 L40 55 L55 48Z" fill="#f59e0b"/>
  <!-- Raven eye -->
  <circle cx="78" cy="52" r="4" fill="#fff"/>
  <circle cx="79" cy="52" r="2" fill="#000"/>
  <!-- Wing detail -->
  <path d="M100 85 C90 100 85 120 88 140 C95 130 105 120 110 105Z" fill="rgba(0,0,0,0.2)"/>
  <!-- Tech dots -->
  <circle cx="30" cy="30" r="3" fill="#7c3aed" opacity="0.6">
    <animate attributeName="opacity" values="0.6;0.2;0.6" dur="2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="170" cy="30" r="3" fill="#2563eb" opacity="0.6">
    <animate attributeName="opacity" values="0.2;0.6;0.2" dur="2s" repeatCount="indefinite"/>
  </circle>
  <circle cx="170" cy="170" r="3" fill="#7c3aed" opacity="0.4">
    <animate attributeName="opacity" values="0.4;0.8;0.4" dur="2.5s" repeatCount="indefinite"/>
  </circle>
  <circle cx="30" cy="170" r="3" fill="#2563eb" opacity="0.4">
    <animate attributeName="opacity" values="0.8;0.4;0.8" dur="2.5s" repeatCount="indefinite"/>
  </circle>
</svg>

# Raven AI

**Personal AI Assistant — 24/7 \ Multi-Channel \ Multi-Provider LLM**

[![GitHub Release](https://img.shields.io/badge/version-0.1.0--dev-purple?style=flat-square&logo=github)](https://github.com/ssrjkk/raven)
[![Python](https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](https://github.com/ssrjkk/raven/pulls)
[![OpenRouter](https://img.shields.io/badge/OpenRouter-Native-ff6b35?style=flat-square)](https://openrouter.ai)

<p>
  <b>Telegram</b> · <b>Discord</b> · <b>WebChat</b> · <b>Slack</b> · <b>Matrix</b>
</p>

---

**Raven** — персональный AI-ассистент, работающий 24/7. Подключается ко всем мессенджерам, использует любые LLM-модели через OpenRouter, Anthropic, OpenAI или локальный Ollama. Python-first, с векторной памятью из коробки и веб-интерфейсом.

</div>

---

## Features

| Feature | Raven AI | OpenClaw |
|---------|----------|----------|
| Language | Python 3.12+ | TypeScript/Node.js |
| Architecture | asyncio monorepo | Node.js monorepo |
| Memory | Built-in (ChromaDB) | Plugin only |
| Web UI | Built-in (React + Alpine.js) | Plugin only |
| OpenRouter | Native (all models, no config) | Via plugin |
| Plugin System | 1 file = 1 plugin | Markdown + code |
| RAM Usage | ~150MB baseline | ~400MB baseline |
| Multi-Agent | Per-channel configurable | Per-channel |
| Voice | Roadmap v2 | Built-in |

## Quickstart

```bash
# 1. Install
pip install raven-ai

# 2. Configure
cp .env.example .env
# Edit .env with your API keys
raven onboard

# 3. Run
raven start
```

Open **http://localhost:18888** for the web UI.

### Docker

```bash
docker compose -f deploy/docker-compose.yml up
```

### From source (development)

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven
pip install -e .
pip install -r requirements-dev.txt  # optional: dev dependencies
raven start
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
| Signal | 🚧 Roadmap | signal-cli |
| iMessage | 🚧 Roadmap | pyobjc |

## Models

```
openrouter/anthropic/claude-3-opus     Best reasoning
openrouter/anthropic/claude-3-haiku    Fast & cheap
openrouter/openai/gpt-4o               GPT-4 Omni
openrouter/meta-llama/llama-3-70b      Open source
claude-3-haiku-20240307                Direct Anthropic
gpt-4o                                 Direct OpenAI
ollama/llama3                          Local (Ollama)
```

Set `DEFAULT_MODEL` in `.env` or prefix any model with `openrouter/`.

## Plugins

| Plugin | Description |
|--------|-------------|
| **memory** | ChromaDB vector store — remember, recall, forget |
| **browser** | Playwright web browsing, screenshots, DDG search |
| **cron** | APScheduler — cron-based task scheduling |
| **code** | Sandboxed Python execution (no network, timeout, tmpdir) |
| **files** | File reading and manipulation |
| **api** | HTTP requests (GET, POST, PUT, DELETE) |
| **ocr** | Tesseract OCR — text extraction from images |
| **process** | System process management (run, list, kill) |

### Writing a plugin

```python
# plugins/myplugin/plugin.py
PLUGIN_NAME = "myplugin"
PLUGIN_DESCRIPTION = "Does something cool"

async def my_tool(param1: str, param2: int = 42) -> str:
    """Tool description. Args: param1 (str): First param, param2 (int): Second param"""
    return f"Result: {param1} = {param2}"
```

Type hints → JSON Schema. One file = one plugin. No registration needed.

## CLI

```
raven start                    Launch the gateway
raven start --port 9090        Custom web port
raven stop                     Stop daemon
raven status                   System status
raven doctor                   Diagnostics
raven onboard                  Setup wizard
raven pairing list             Pending pairings
raven pairing approve CODE     Approve user
raven models list              Available models
raven plugins list             Loaded plugins
raven history SESSION_ID       View messages
```

## Security

- **DM Policy**: `pairing` (default), `open`, or `closed`
- **Pairing**: Users send `/pair CODE` to authorize
- **Allowlist**: Set `ALLOWED_USERS=telegram:123,discord:456`
- **Sandbox**: Code execution isolated (no network, temp dir, 30s timeout)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DEFAULT_MODEL` | `openrouter/anthropic/claude-3-haiku` | Default LLM model |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token |
| `DISCORD_BOT_TOKEN` | — | Discord bot token |
| `DM_POLICY` | `pairing` | Access policy |
| `WEB_PORT` | `18888` | Web UI port |
| `DB_PATH` | `~/.raven/raven.db` | SQLite path |
| `VECTOR_DB_PATH` | `~/.raven/chroma` | Vector store path |

## Architecture

```
raven-ai/
├── core/              Event bus, agent loop, LLM router
│   ├── agent/         ReAct agent, multi-agent registry
│   └── gateway/       Message routing, session management
├── channels/          Messaging adapters (Telegram, Discord, WebChat)
├── plugins/           Plugin system (memory, browser, cron, code, files, api, ocr, process)
├── web/               TypeScript frontend (React + Vite)
├── desktop/           Electron desktop shell
├── extension/         Chrome browser extension
├── cli/               Command-line interface
└── deploy/            Docker, systemd, macOS launchd
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12+, FastAPI, asyncio, SQLite |
| **LLM** | OpenRouter, Anthropic, OpenAI, Ollama |
| **Memory** | ChromaDB (vector), SQLite (relational) |
| **Web** | React 19, TypeScript, Vite, Tailwind CSS v4 |
| **Desktop** | Electron 33 |
| **Browser** | Chrome Extension Manifest V3 |
| **Deploy** | Docker, systemd, launchd |

## Roadmap

**v0.2** — Voice & Mobile
- Wake word (Porcupine), TTS (ElevenLabs)
- Signal (signal-cli)
- iOS/Android push notifications

**v0.3** — Advanced
- Canvas visual workspace
- Multi-agent orchestration
- Image generation (DALL-E, SD)
- RAG over user documents

**v0.4** — Enterprise
- Kubernetes helm chart
- PostgreSQL, Redis support
- Team collaboration
- Audit logging, RBAC

## Why Raven?

1. **Python-first** — Easier AI/ML integration, larger developer ecosystem
2. **Built-in memory** — Vector DB included, not a bolt-on plugin
3. **Native OpenRouter** — All models through one API, zero config
4. **Web UI included** — Not just messenger bots
5. **Simple plugins** — One Python file = one plugin
6. **Lower cost** — ~150MB RAM vs Node.js 400MB+

## Contact

**Author:** [@ssrjkk](https://github.com/ssrjkk)

<p align="center">
  <a href="https://github.com/ssrjkk/raven"><img src="https://img.shields.io/badge/GitHub-ssrjkk/raven-181717?style=for-the-badge&logo=github" alt="GitHub"></a>
  <a href="https://github.com/ssrjkk"><img src="https://img.shields.io/badge/Author-@ssrjkk-blue?style=for-the-badge" alt="Author"></a>
</p>

---

## License

MIT © 2026 [@ssrjkk](https://github.com/ssrjkk)

---

<p align="center">
  <b>🐦 Raven AI</b> — Your personal AI, always connected.
</p>

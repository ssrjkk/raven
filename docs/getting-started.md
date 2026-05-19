# Getting Started

## Installation

```bash
pip install raven-ai
```

Or install from source:

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
```

## Quick Start

### 1. Onboard

Run the interactive setup wizard:

```bash
raven onboard
```

This guides you through:
- LLM provider configuration (OpenAI, Anthropic, OpenRouter, Ollama)
- Channel setup (Telegram, Discord, etc.)
- Security preferences (DM policy, tool execution)
- Port configuration

### 2. Start the Gateway

```bash
raven start
```

The gateway listens on `http://localhost:18888` by default.

### 3. Install as a Service

```bash
raven service install
raven service start
```

### 4. Send a Message

```bash
raven agent --message "Hello! What can you do?"
```

## Docker

```bash
docker compose up -d
```

## Configuration

Configuration is managed through:
- `.env` file for environment variables
- `~/.raven/config.json` for persistent settings
- CLI flags for runtime options

See the [Configuration](configuration.md) page for all options.

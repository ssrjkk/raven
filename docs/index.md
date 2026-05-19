# Raven AI

**Personal AI Assistant — Any Channel. Any Platform.**

Raven AI is a personal AI assistant you run on your own infrastructure. It connects to the messaging channels you already use — Telegram, Discord, Slack, WhatsApp, and more — and provides a unified AI-powered assistant experience.

## Key Features

- **Multi-channel** — 15+ messaging channels supported
- **Multi-agent** — Route users to purpose-specific agents
- **Tool system** — Plugin-powered tool registry with 30+ built-in tools
- **Security first** — DM pairing, context visibility, sandboxed execution
- **Self-hosted** — Run on your own hardware, own your data
- **Extensible** — Plugin SDK, skill registry, webhook system

## Quick Start

```bash
pip install raven-ai

raven onboard
raven start
```

## Architecture

Raven uses a **Gateway** architecture:
- **Gateway** — central message orchestrator
- **Channels** — messaging platform adapters
- **Agents** — session-aware AI workers with tool access
- **Tools** — capability plugins (files, code, browser, etc.)
- **Security** — policy engine, audit, PII redaction

## Supported Channels

Telegram · Discord · Slack · WhatsApp · Matrix · IRC · Signal · Google Chat · Feishu · LINE · Microsoft Teams · WebChat

## License

MIT

# Channels Overview

Raven AI connects to 15+ messaging platforms. Each channel is implemented as a `BaseChannel` subclass.

## Supported Channels

| Channel | Type | Reconnection | Status |
|---------|------|-------------|--------|
| Telegram | Polling (python-telegram-bot) | Library-managed | Stable |
| Discord | Gateway (discord.py) | Library-managed | Stable |
| Slack | Webhook/Events API | Stateless | Stable |
| WhatsApp | Cloud API Webhook | Stateless | Stable |
| Matrix | Client-Server API | Built-in retry | Stable |
| IRC | Raw sockets | Built-in retry | Stable |
| Signal | REST API | Stateless | Stable |
| Google Chat | Webhook | Stateless | Stable |
| Feishu | Webhook + API | Stateless | Stable |
| LINE | Webhook | Stateless | Stable |
| Microsoft Teams | Webhook | Stateless | Stable |
| WebChat | WebSocket | Client reconnect | Stable |

## Architecture

Each channel:
1. Receives messages via its platform-specific mechanism
2. Normalizes them into `IncomingMessage` objects
3. Passes them to the Gateway for processing
4. Sends responses back through the platform

## EnterpriseChannel Base

Channels that support webhooks extend `EnterpriseChannel`, which provides:
- Rate limiting (token bucket)
- Retry with exponential backoff
- Stats tracking (sent, failed, reconnects)
- Audit logging

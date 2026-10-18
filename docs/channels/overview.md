# Channels Overview

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven AI connects to 15 messaging platforms. Each channel is implemented as a `BaseChannel` subclass.

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
| GitHub | Webhook | Stateless | Stable |
| GitLab | Webhook | Stateless | Stable |
| Email | IMAP/SMTP | Polling | Stable |
| WebChat | WebSocket | Client reconnect | Stable |

## Inbound Verification

A webhook route checks the delivery before it parses the payload. Each one prefers its own
platform secret and otherwise accepts the shared HMAC of the raw body in
`X-Webhook-Signature` (keyed with `WEB_SECRET_KEY`). With neither secret set the route answers
403 to everything, so an unverified payload is refused rather than parked in a low-priority queue.

| Route | What it checks | Own secret |
|-------|----------------|------------|
| `/api/webhooks/slack/events` | `X-Slack-Signature` = `v0=` + HMAC-SHA256 of `v0:<timestamp>:<body>`, timestamp window 300 s | `SLACK_SIGNING_SECRET` |
| `/api/webhooks/github` | `X-Hub-Signature-256` = `sha256=` + hex HMAC of the raw body | `GITHUB_WEBHOOK_SECRET` |
| `/api/webhooks/gitlab` | `X-Gitlab-Token` compared to the shared token | `GITLAB_WEBHOOK_SECRET` |
| `/api/webhooks/line` | `X-Line-Signature` = base64 HMAC-SHA256 of the raw body | `LINE_CHANNEL_SECRET` |
| `/api/webhooks/feishu` | `X-Lark-Signature` = SHA-256 of `timestamp + nonce + encrypt key + body`, and an echo of the `url_verification` challenge | `FEISHU_ENCRYPT_KEY` |
| `/api/webhooks/whatsapp` | `X-Hub-Signature-256` on the POST; the `GET` handshake compares `hub.verify_token`, which travels in a query string and so keeps its own variable | `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` |
| `/api/webhooks/teams`, `/googlechat`, `/signal`, `/github-actions`, `/allure`, `/generic` | `X-Webhook-Signature` | — shared key only |

The remaining adapters open their own connection and carry no inbound signature: Telegram and
Discord authenticate with the bot token, Matrix with an access token, IRC with an optional
server password, Email with the IMAP login, and WebChat with `WEB_SECRET_KEY` or an issued JWT
on the WebSocket handshake.

Outbound-only settings — `TEAMS_WEBHOOK_URL`, `GOOGLECHAT_WEBHOOK_URL`, `FEISHU_WEBHOOK_URL` —
carry replies; they do not admit anyone.

## Optional Dependencies and Configuration

Four adapters need a package extra and environment variables. Without them the
gateway logs a warning at startup and skips the channel — everything else still runs.

| Channel | Install extra | Configuration |
|---------|---------------|---------------|
| Telegram | — (core dependency) | `TELEGRAM_BOT_TOKEN` |
| Discord | `pip install 'raven-agent[discord]'` | `DISCORD_BOT_TOKEN` |
| Slack | `pip install 'raven-agent[slack]'` | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` |
| Email | `pip install 'raven-agent[email]'` | `EMAIL_SMTP_HOST`, `EMAIL_SMTP_USER`, `EMAIL_IMAP_HOST`, `EMAIL_IMAP_USER` (plus optional ports, `EMAIL_INBOX_FOLDER`, `EMAIL_POLL_INTERVAL`) |

Email polls `EMAIL_INBOX_FOLDER` for unseen messages every `EMAIL_POLL_INTERVAL`
seconds (5 unseen messages max per poll) and marks each one seen before handing it to
the gateway, so a message that fails to parse cannot be refetched forever. Incoming
mail opens a session named `email:<sender>:default`; a reply is addressed from that
session id back through SMTP. `EMAIL_SMTP_PORT=465` uses implicit TLS, any other port
upgrades with STARTTLS.

`raven doctor` lists every channel whose environment variables are present.

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

# Enterprise Audit Plan

## Phase 1 — Core Infrastructure (HIGH)
- [x] Multi-channel inbox (Telegram, Discord, WebChat, Slack, WhatsApp, Matrix)
- [x] Model failover with weighted fallback
- [x] Sandboxing (direct, subprocess, Docker)
- [x] Skills/playbooks system
- [x] Webhook automation
- [x] Chat commands (/status, /new, /reset, /help, /skills, /pair)
- [x] Structured logging, health checks, Prometheus metrics
- [x] Rate limiting, auth middleware
- [x] Database migrations
- [ ] Multi-agent routing (per-channel/peer agent assignment)
- [ ] Agent workspace system (AGENTS.md, SOUL.md, TOOLS.md injection)
- [ ] All chat commands: /compact, /think <level>, /verbose, /trace, /usage, /restart, /activation
- [ ] Session tools plugin: sessions_list, sessions_history, sessions_send, sessions_spawn
- [ ] GitHub Actions CI (lint + test)
- [ ] Dockerfile + docker-compose.yml

## Phase 2 — More Channels (MEDIUM)
- [ ] Google Chat channel
- [ ] Signal channel
- [ ] IRC channel
- [ ] Microsoft Teams channel
- [ ] Feishu/Lark channel
- [ ] LINE channel
- [ ] Telegram supergroup support

## Phase 3 — Enterprise Polish (LOW)
- [ ] CLI parity: agent command, nodes command, devices command
- [ ] Per-channel allowlist (allowFrom configuration)
- [ ] Remote access / Tailscale support
- [ ] Gmail pub/sub automation
- [ ] Full config reference documentation
- [ ] Session compaction (/compact)

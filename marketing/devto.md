
**Title:** How I built a 15-channel self-hosted AI assistant in pure Python

**Body:**
Building an AI assistant is easy. Building an **enterprise-grade, self-hosted AI orchestrator** that runs 24/7 across 15 channels is a different story.

In this article, I want to share the architecture behind **Raven AI**, an open-source project I've been building.

## The Problem
Most AI tools are just wrappers around an API. They don't have memory, they can't execute tasks autonomously, and they certainly don't integrate with your self-hosted infrastructure. I wanted a system that could think, plan, and act across Telegram, Discord, Slack, and my local environment, all while keeping my data 100% private.

## The Architecture
Raven AI is a **single-process Python monolith**: one FastAPI gateway that connects every channel to the agent core and serves the React dashboard from the same process.

### 1. The Gateway (Python 3.11+ + FastAPI)
The brain of the operation. It handles channel adapters, LLM orchestration, RAG (a local-first JSON embedding store + BM25, no external vector DB), the task/monitor/routine engines, and the plugin system. A `ChannelGuardian` supervises every channel with heartbeats, per-channel/per-user token-bucket rate limiting, and automatic restarts.

### 2. The Agent Core
A ReAct agent plans and calls one of 30+ tools (files, shell, HTTP, DB, browser, MCP, and more). A `ModelFailover` layer with circuit breakers rotates across 10 providers (OpenRouter, Anthropic, OpenAI, Ollama, Groq, Bedrock, Vertex, and others) so a dead provider never takes the assistant down.

### 3. The Coding Agent (RavenCode)
This is my favorite part. It's an interactive coding agent that uses **LSP auto-enrichment**. When you ask it to write code, it doesn't just guess; it starts LSP servers (pyright, typescript-language-server) to gather document symbols and understand your entire codebase context.

### 4. The Frontend (React 19 + Vite 6 + Tailwind 4)
The web dashboard is a React SPA — chat, IDE, monitors, tasks, analytics, a command palette (Ctrl+K), and a git viewer with a side-by-side diff. It's built with Vite and served directly by the FastAPI gateway.

## Key Features
- **15 Channels:** One brain, everywhere.
- **Voice I/O:** "Hey Raven" wake word detection using local Whisper.
- **Enterprise Security:** sandbox profiles with strict tool policies, SSRF guards on every outbound request, and RBAC.
- **Local-First:** 100% offline capable using Ollama; SQLite by default, PostgreSQL optional.

## Check it out
The project is fully open-source.
👉 **GitHub:** https://github.com/ssrjkk/raven
👉 **Landing Page:** https://ssrjkk.github.io/raven/

Let me know what you think about the single-process Python approach in the comments!

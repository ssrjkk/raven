
**Title:** I built an enterprise-grade, self-hosted AI assistant that runs 24/7 across 15 channels (pure Python + React)

**Body:**
Hey everyone,

I've been working on **Raven AI**, a fully self-hosted, enterprise-grade AI orchestrator. I wanted something that wasn't just a wrapper around the OpenAI API, but a true autonomous agent that lives on my server and integrates into my entire digital life.

**Key features I'm proud of:**
- **15 Channels out of the box:** Telegram, Discord, Slack, WhatsApp, Matrix, Signal, Teams, Google Chat, IRC, Feishu, LINE, Email, GitHub, GitLab, and a built-in web chat. One brain, everywhere.
- **RavenCode Agent:** An interactive coding agent with LSP auto-enrichment (Pyright, TypeScript, etc.). It actually understands your codebase context.
- **Enterprise Security:** sandbox profiles, RBAC, SSRF guards on every outbound request, and strict tool policies. Your data never leaves your server.
- **Local-First RAG:** Semantic search across your documents using a local JSON embedding store + BM25. 100% offline capable with Ollama.
- **Voice I/O:** "Hey Raven" wake word detection using local Whisper STT and Edge/gTTS.

**Tech Stack:**
Python 3.11+ (FastAPI, single process) + React 19 + Vite 6 + Tailwind 4 + SQLite (PostgreSQL optional).

It's completely free, open-source, and designed for power users who want total control.

Check it out: [https://github.com/ssrjkk/raven](https://github.com/ssrjkk/raven)
Live Demo/Landing: [https://ssrjkk.github.io/raven/](https://ssrjkk.github.io/raven/)

Would love to hear your feedback on the architecture or feature requests!

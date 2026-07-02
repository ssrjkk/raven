#!/usr/bin/env python3
"""
Raven AI Growth Engine
Generates a stylish Landing Page for GitHub Pages and viral marketing posts.
"""
import os

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raven AI - Enterprise-Grade Self-Hosted AI Assistant</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background: radial-gradient(circle at top right, #0f172a, #000000); color: #e2e8f0; }
        @keyframes pulse-neon {
            0%, 100% { text-shadow: 0 0 10px #06b6d4, 0 0 20px #06b6d4; }
            50% { text-shadow: 0 0 20px #06b6d4, 0 0 30px #06b6d4, 0 0 40px #06b6d4; }
        }
        .neon-text { animation: pulse-neon 3s infinite; }
        .glass { background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); }
        .gradient-text { background: linear-gradient(to right, #22d3ee, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    </style>
</head>
<body class="font-sans">
    <!-- Nav -->
    <nav class="fixed w-full glass z-50">
        <div class="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
            <div class="text-2xl font-bold neon-text">\U0001f426 Raven AI</div>
            <div class="space-x-6 hidden md:flex">
                <a href="#features" class="hover:text-cyan-400 transition">Features</a>
                <a href="#stack" class="hover:text-cyan-400 transition">Stack</a>
                <a href="#architecture" class="hover:text-cyan-400 transition">Architecture</a>
                <a href="https://github.com/ssrjkk/raven" class="px-4 py-2 bg-cyan-500 text-black rounded-lg font-bold hover:bg-cyan-400 transition">GitHub</a>
            </div>
        </div>
    </nav>

    <!-- Hero -->
    <header class="pt-32 pb-20 px-4 text-center max-w-5xl mx-auto">
        <h1 class="text-5xl md:text-7xl font-extrabold mb-6 gradient-text">
            The Last AI Assistant You'll Ever Need.
        </h1>
        <p class="text-xl text-gray-400 mb-10 max-w-3xl mx-auto">
            Raven AI is an enterprise-grade, 100% self-hosted AI orchestrator. It thinks, plans, and acts across 25+ channels, executes code with LSP enrichment, and runs entirely on your own hardware.
        </p>
        <div class="flex flex-col sm:flex-row gap-4 justify-center">
            <a href="https://github.com/ssrjkk/raven" class="px-8 py-4 bg-gradient-to-r from-cyan-500 to-blue-600 text-white rounded-xl font-bold text-lg shadow-lg shadow-cyan-500/20 hover:scale-105 transition">
                <i class="fab fa-github mr-2"></i> Star on GitHub
            </a>
            <a href="#quickstart" class="px-8 py-4 glass rounded-xl font-bold text-lg hover:bg-gray-800 transition">
                <i class="fas fa-rocket mr-2"></i> Quickstart
            </a>
        </div>
        <div id="quickstart" class="mt-12 glass rounded-2xl p-6 max-w-2xl mx-auto text-left font-mono text-sm">
            <div class="flex space-x-2 mb-4">
                <div class="w-3 h-3 rounded-full bg-red-500"></div>
                <div class="w-3 h-3 rounded-full bg-yellow-500"></div>
                <div class="w-3 h-3 rounded-full bg-green-500"></div>
            </div>
            <code class="text-green-400">$ pip install raven-agent</code><br>
            <code class="text-green-400">$ raven onboard</code><br>
            <code class="text-gray-400"># Interactive setup wizard (LLM, Telegram, channels)</code><br>
            <code class="text-green-400">$ raven start</code><br>
            <code class="text-cyan-400">\U0001f680 Raven AI is running on http://localhost:18888</code>
        </div>
    </header>

    <!-- Features -->
    <section id="features" class="py-20 px-4 max-w-7xl mx-auto">
        <h2 class="text-4xl font-bold text-center mb-16 neon-text">Unmatched Capabilities</h2>
        <div class="grid md:grid-cols-3 gap-8">
            <div class="glass p-8 rounded-2xl hover:border-cyan-500/50 transition">
                <i class="fas fa-network-wired text-4xl text-cyan-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">25+ Channels</h3>
                <p class="text-gray-400">Telegram, Discord, Slack, WhatsApp, Matrix, Signal, Teams, and 15+ more. One brain, everywhere.</p>
            </div>
            <div class="glass p-8 rounded-2xl hover:border-purple-500/50 transition">
                <i class="fas fa-code text-4xl text-purple-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">RavenCode Agent</h3>
                <p class="text-gray-400">Interactive REPL with LSP auto-enrichment (Pyright, Go, TS, Rust). It understands your codebase.</p>
            </div>
            <div class="glass p-8 rounded-2xl hover:border-green-500/50 transition">
                <i class="fas fa-shield-alt text-4xl text-green-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">Enterprise Security</h3>
                <p class="text-gray-400">5 sandbox profiles, RBAC, Fernet encryption, and strict tool policies. Your data never leaves your server.</p>
            </div>
            <div class="glass p-8 rounded-2xl hover:border-yellow-500/50 transition">
                <i class="fas fa-microphone text-4xl text-yellow-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">Voice I/O & Wake Words</h3>
                <p class="text-gray-400">"Hey Raven". Local Whisper STT and Edge/gTTS TTS. True hands-free autonomous operation.</p>
            </div>
            <div class="glass p-8 rounded-2xl hover:border-red-500/50 transition">
                <i class="fas fa-project-diagram text-4xl text-red-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">RavenFlow Orchestrator</h3>
                <p class="text-gray-400">Multi-agent gateway daemon with routing engine, session management, and WebSocket streaming.</p>
            </div>
            <div class="glass p-8 rounded-2xl hover:border-blue-500/50 transition">
                <i class="fas fa-brain text-4xl text-blue-400 mb-4"></i>
                <h3 class="text-2xl font-bold mb-3">Local-First RAG</h3>
                <p class="text-gray-400">Semantic search across your documents. ChromaDB/Qdrant vector stores. 100% offline capable.</p>
            </div>
        </div>
    </section>

    <!-- Tech Stack -->
    <section id="stack" class="py-20 px-4 bg-gray-900/50">
        <div class="max-w-7xl mx-auto text-center">
            <h2 class="text-4xl font-bold mb-16 neon-text">Built for Scale & Performance</h2>
            <div class="flex flex-wrap justify-center gap-6 text-2xl text-gray-400">
                <div class="glass px-6 py-3 rounded-full"><i class="fab fa-python text-yellow-400 mr-2"></i>Python 3.13</div>
                <div class="glass px-6 py-3 rounded-full"><i class="fab fa-golang text-blue-400 mr-2"></i>Go 1.26</div>
                <div class="glass px-6 py-3 rounded-full"><i class="fab fa-react text-cyan-400 mr-2"></i>React 19</div>
                <div class="glass px-6 py-3 rounded-full"><i class="fab fa-rust text-orange-500 mr-2"></i>Tauri (Rust)</div>
                <div class="glass px-6 py-3 rounded-full"><i class="fas fa-database text-green-400 mr-2"></i>SQLite + NATS</div>
                <div class="glass px-6 py-3 rounded-full"><i class="fab fa-docker text-blue-500 mr-2"></i>Docker & K8s</div>
            </div>
        </div>
    </section>

    <!-- Star History -->
    <section class="py-20 px-4 max-w-5xl mx-auto text-center">
        <h2 class="text-4xl font-bold mb-10 neon-text">Join the Flock</h2>
        <p class="text-gray-400 mb-10 text-lg">Raven AI is open-source and growing. Star the repo to follow our journey.</p>
        <div class="glass p-8 rounded-2xl">
            <img src="https://api.star-history.com/svg?repos=ssrjkk/raven&type=Date" alt="Star History Chart" class="mx-auto max-w-full h-64 rounded-lg">
        </div>
    </section>

    <!-- Footer -->
    <footer class="py-10 text-center text-gray-500 border-t border-gray-800">
        <p>\u00a9 2026 Raven AI. Open Source under MIT License.</p>
        <div class="mt-4 space-x-6 text-2xl">
            <a href="https://github.com/ssrjkk/raven" class="hover:text-white transition"><i class="fab fa-github"></i></a>
        </div>
    </footer>
</body>
</html>
"""

REDDIT_POST = """
**Title:** I built an enterprise-grade, self-hosted AI assistant that runs 24/7 across 25+ channels (Python, Go, Rust, React)

**Body:**
Hey everyone,

I've been working on **Raven AI**, a fully self-hosted, enterprise-grade AI orchestrator. I wanted something that wasn't just a wrapper around the OpenAI API, but a true autonomous agent that lives on my server and integrates into my entire digital life.

**Key features I'm proud of:**
- **25+ Channels out of the box:** Telegram, Discord, Slack, WhatsApp, Matrix, Signal, Teams, and 15+ more. One brain, everywhere.
- **RavenCode Agent:** An interactive REPL coding agent with LSP auto-enrichment (Pyright, Go, TS, Rust). It actually understands your codebase context.
- **Enterprise Security:** 5 sandbox profiles, RBAC, Fernet encryption, and strict tool policies. Your data never leaves your server.
- **Local-First RAG:** Semantic search across your documents using ChromaDB/Qdrant. 100% offline capable with Ollama.
- **Voice I/O:** "Hey Raven" wake word detection using local Whisper STT and Edge/gTTS.

**Tech Stack:**
Python 3.13 (FastAPI) + Go 1.26 (Gateway/Monitors) + React 19 + Tauri (Rust) + NATS + SQLite.

It's completely free, open-source, and designed for power users who want total control.

Check it out: [https://github.com/ssrjkk/raven](https://github.com/ssrjkk/raven)
Live Demo/Landing: [https://ssrjkk.github.io/raven/](https://ssrjkk.github.io/raven/)

Would love to hear your feedback on the architecture or feature requests!
"""

HN_POST = """
**Title:** Raven AI \u2013 A self-hosted, multi-agent AI orchestrator with LSP-enriched coding agent

**Body:**
Show HN: Raven AI

I've built an enterprise-grade, self-hosted AI assistant designed to run 24/7 on your own hardware. Instead of just being a chatbot, it's a full orchestrator with a multi-agent gateway (RavenFlow), a coding agent with LSP enrichment (RavenCode), and a visual canvas workspace.

**Architecture highlights:**
- **Backend:** Python 3.13 (FastAPI) for the core agent, Go 1.26 for the high-performance gateway, monitors, and auth service.
- **Message Broker:** NATS + JetStream for event-driven communication between agents and channels.
- **Frontend:** React 19 + Vite + Tailwind, bundled into a Tauri (Rust) desktop app.
- **Security:** 5 sandbox profiles (main, non-main, code-exec, web-browsing, read-only) with runtime tool allow/deny policies.
- **Local-First:** Supports Ollama for 100% offline operation, with ChromaDB/Qdrant for RAG.

It supports 25+ channels (Telegram, Discord, Slack, Matrix, etc.) and includes tools for task execution, monitoring, and scheduled routines.

GitHub: https://github.com/ssrjkk/raven
Landing: https://ssrjkk.github.io/raven/

I'm particularly interested in feedback on the NATS integration and the LSP enrichment approach for the coding agent.
"""

DEV_TO_POST = """
**Title:** How I built a 25+ channel AI assistant using Python, Go, and React

**Body:**
Building an AI assistant is easy. Building an **enterprise-grade, self-hosted AI orchestrator** that runs 24/7 across 25+ channels is a different story.

In this article, I want to share the architecture behind **Raven AI**, an open-source project I've been building.

## The Problem
Most AI tools are just wrappers around an API. They don't have memory, they can't execute tasks autonomously, and they certainly don't integrate with your self-hosted infrastructure. I wanted a system that could think, plan, and act across Telegram, Discord, Slack, and my local environment, all while keeping my data 100% private.

## The Architecture
Raven AI is built on a modular, microservices-inspired architecture:

### 1. The Core (Python 3.13 + FastAPI)
The brain of the operation. It handles the LLM orchestration, RAG (using ChromaDB/Qdrant), and the plugin system.

### 2. The Gateway (Go 1.26)
To handle the high concurrency of 25+ channels (Telegram, Discord, Slack, Matrix, Signal, etc.), I built `RavenFlow` in Go. It acts as a multi-agent gateway daemon with a routing engine, session management, and WebSocket streaming.

### 3. The Coding Agent (RavenCode)
This is my favorite part. It's an interactive REPL coding agent that uses **LSP auto-enrichment**. When you ask it to write code, it doesn't just guess; it starts LSP servers (pyright, typescript-language-server, gopls) to gather document symbols and understand your entire codebase context.

### 4. The Frontend (React 19 + Tauri)
The web dashboard is built with React 19, Vite 6, and Tailwind CSS. For desktop users, it's wrapped in a Tauri (Rust) shell for native performance.

## Key Features
- **25+ Channels:** One brain, everywhere.
- **Voice I/O:** "Hey Raven" wake word detection using local Whisper.
- **Enterprise Security:** 5 sandbox profiles with strict tool policies.
- **Local-First:** 100% offline capable using Ollama.

## Check it out
The project is fully open-source.
\U0001f449 **GitHub:** https://github.com/ssrjkk/raven
\U0001f449 **Landing Page:** https://ssrjkk.github.io/raven/

Let me know what you think about the Go + Python + NATS stack in the comments!
"""


class RavenGrowthEngine:
    def __init__(self):
        self.docs_dir = "docs"
        self.marketing_dir = "marketing"

    def generate(self):
        os.makedirs(self.docs_dir, exist_ok=True)
        os.makedirs(self.marketing_dir, exist_ok=True)

        with open(os.path.join(self.docs_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(HTML_CONTENT)

        with open(os.path.join(self.marketing_dir, "reddit_selfhosted.md"), "w", encoding="utf-8") as f:
            f.write(REDDIT_POST)

        with open(os.path.join(self.marketing_dir, "hackernews.md"), "w", encoding="utf-8") as f:
            f.write(HN_POST)

        with open(os.path.join(self.marketing_dir, "devto.md"), "w", encoding="utf-8") as f:
            f.write(DEV_TO_POST)

        print("[OK] Raven Growth Engine executed successfully!")
        print("[+] Landing page generated: {}/index.html".format(self.docs_dir))
        print("[+] Marketing posts generated: {}/".format(self.marketing_dir))
        print("")
        print("NEXT STEPS:")
        print("1. Commit the 'docs/' folder to your main branch.")
        print("2. Go to GitHub Repo Settings -> Pages -> Source: Deploy from branch -> main -> /docs.")
        print("3. Copy the posts from 'marketing/' and publish them on Reddit, HN, and Dev.to.")


if __name__ == "__main__":
    engine = RavenGrowthEngine()
    engine.generate()

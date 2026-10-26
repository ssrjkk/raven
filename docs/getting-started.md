# Getting Started

_by [@ssrjkk](https://github.com/ssrjkk)_

## Installation

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
```

### From a release (Windows)

`Raven.exe` is attached to every tag together with `Raven.exe.sha256`, and both carry a build
attestation. Verify the download before running it:

```bash
curl -LO https://github.com/ssrjkk/raven/releases/latest/download/Raven.exe
curl -LO https://github.com/ssrjkk/raven/releases/latest/download/Raven.exe.sha256
sha256sum --check Raven.exe.sha256
```

On Windows itself, `certutil -hashfile Raven.exe SHA256` prints the same digest.

The release also carries a build attestation. This repository is public, so GitHub checks the signing
identity against its issuer allow-list and marks the artifacts verified on the release page; from the
CLI:

```bash
gh attestation verify Raven.exe --repo ssrjkk/raven
```

That statement ties the binary to this repository, the commit the tag points at and the
`Build EXE` workflow run — it says where a file was produced, not that it is safe to run.

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

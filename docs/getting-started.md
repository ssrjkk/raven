---
description: "Install with pipx or Docker, start the gateway, add the MCP server to a client, and set the variables it reads."
---

# Getting Started

_by [@ssrjkk](https://github.com/ssrjkk)_

## Installation

```bash
git clone https://github.com/ssrjkk/raven
cd raven
pip install -e ".[dev]"
```

### Optional providers

The base install runs everything that needs no third-party provider. Providers are imported lazily
and fall back when their package is absent, so a group you did not install is not an error message --
it is a feature that quietly stops running. Install the groups you use:

| Extra | Brings in | What it makes real |
|---|---|---|
| `voice` | sounddevice | microphone capture and the conversation loop |
| `tts` | elevenlabs, gTTS, edge-tts | cloud text-to-speech (falls back to system TTS) |
| `stt` | vosk, SpeechRecognition, openai-whisper, azure-cognitiveservices-speech | speech-to-text providers |
| `speaker` | librosa, speechbrain | speaker verification and the anti-spoof check (spectral flatness, energy ratio, band-profile stability) |
| `search` | duckduckgo-search | web search in ravencode |
| `nlp` | presidio-analyzer | PII entities in the context filter beyond the built-in patterns |
| `logging` | structlog | structured log rendering |
| `tracking` | wandb | W&B mirror of training runs; publishes only with `RAVEN_TRAIN_TRACKING=on` |
| `rag` | sentence-transformers | local embeddings for retrieval |
| `ml` | torch, transformers, peft, datasets | fine-tuning |
| `vector` | chromadb, hnswlib | the vector stores |
| `all` | everything above except `stt`, `speaker`, `nlp`, `tracking`, `ml`, `rag` | a full non-torch install |

`tests/test_dependency_declarations.py` fails the build if shipped code starts importing a package
that no group declares, which is the control that was missing when the anti-spoof check went silent.

An optional import that is absent is reported, not hidden: without `speaker`, `voice_verify` says
`Anti-spoof: NOT evaluated` and `/api/voice/verify` answers `anti_spoof_checked: false`, because a
verification that never ran must not read as a verification that passed. The same applies to `nlp`:
without it `raven doctor` answers `pii_redaction: regex-only: N patterns, no named-entity
recognition` instead of reporting redaction as fully active -- the built-in patterns still run,
entity detection does not.

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

It is also not a code-signing certificate. Windows 11 with Smart App Control in enforcement mode
blocks an unsigned executable, so a verified release can still refuse to start on such a machine, and
self-signing does not satisfy the policy either. Run from source instead (`pip install -e .`, then
`python -m raven`), or turn Smart App Control off under Windows Security → App & browser control.
Turning it off cannot be undone without reinstalling Windows, so that is the operator's decision —
nothing in the installer or the startup path makes it for them.

## Quick Start

No API key at all? `raven setup --free --experimental --yes` builds a local Ollama stack with the
bundled uncensored Qwen3.5-9B instead of asking for one: [Free Offline Model](local-models.md).

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

`install` registers and starts the service for your platform (Windows needs `pywin32` and an
elevated shell). Per-platform details: [CLI reference](cli.md).

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

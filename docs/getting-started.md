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
| `speaker` | librosa, speechbrain | speaker verification, including the band-consistency anti-spoof check |
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

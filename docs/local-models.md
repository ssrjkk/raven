---
description: "Run Raven on the bundled uncensored Qwen3.5-9B: the hardware it needs, the one command that pulls it, and how to verify or revert."
---

# Free Offline Model

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven ships one model by reference, not by bytes: an uncensored Qwen3.5-9B that runs locally on
Ollama, costs nothing per token and needs no API key. The weights are not in git — the first command
that asks for them downloads them once, and every later start uses what is already on disk.

| | |
|---|---|
| Reference | `hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF:Q4_K_M` |
| Download | 5.63 GB, one time |
| Licence | apache-2.0 along the whole chain: `unsloth/Qwen3.5-9B` → `Jackrong/DeepSeek-V4-Pro-Qwen3.5-9B` → `xtools-at/…-UNCENSORED-heretic` → the mradermacher GGUF |
| Runtime | Ollama, local. Raven talks to `OLLAMA_BASE_URL` (`http://localhost:11434` by default) |
| Owner of the logic | `raven/core/heretic_model.py` — the reference, the hardware answer and the switch |

## What the machine needs

The preflight answers in numbers before anything is downloaded, and the same numbers are printed by
`raven doctor`, `raven models list` and the Admin card:

| Check | Threshold | Why |
|---|---|---|
| Free disk on the weights volume | 8 GB | 5.63 GB of weights plus room to unpack them |
| Total RAM | 8 GB | a 9B at Q4_K_M has to be resident to answer at a usable speed |
| Free RAM, when VRAM is below 8000 MB | 6 GB | with nothing to offload to, the weights live in RAM; a full box pages on every token |
| GPU | optional | 8000 MB of VRAM or more takes the layers off the CPU |

The weights volume is `OLLAMA_MODELS` when it is set, otherwise `~/.ollama`. Memory is read with
`GlobalMemoryStatusEx` on Windows and `sysconf` elsewhere, VRAM with `nvidia-smi`, disk with
`shutil.disk_usage` — `wmic` was removed in Windows 11 24H2 and answers zero, so nothing here uses it.

A refused preflight is a refusal, not a warning: an 8 GB laptop with 1.4 GB free and no GPU will not
run this model, and the command says exactly that. `--force` overrides it and the model will page.
CPU-only inference works on a machine with the RAM for it; expect it to be slow.

## One command

```bash
git clone https://github.com/ssrjkk/raven.git
cd raven
pip install -e .
raven setup --free --experimental --yes
raven start
```

`raven setup --free --experimental --yes` does the whole path: installs Ollama if it is missing
(Windows: the official `OllamaSetup.exe`, 1858 MB, silent; Linux: the official `install.sh`; macOS:
install it yourself with `brew install ollama`), starts `ollama serve`, pulls the 5.63 GB, writes
`raven.json`, `opencode.json` and `.env`, and creates `workspace/`, `plugins/` and `data/`.
`raven start` then serves the gateway and the web UI on http://localhost:18888.

Ollama already installed? One command is enough:

```bash
raven models enable-heretic --yes     # pull if missing, then write the switch
raven start
```

`raven start --ghost` is the same gateway with external calls refused. It keeps the local model you
configured — ghost mode replaces a *hosted* name with one Ollama actually serves, preferring the
bundled model, and never substitutes a model for the one you just downloaded.

If the pull fails or passes its 30-minute limit, `setup` still writes the configs, prints
`configured, weights missing` instead of `Ready`, and exits 1. Ollama keeps what it downloaded, so
`ollama pull <reference>` resumes rather than restarts.

Without `--yes` the download is confirmed on a terminal. On a pipe — a script, a CI job — it is
refused: `setup` then configures the model this hardware runs and pulls that one instead, saying so
before it starts, rather than writing a switch for weights that are not there. `raven start` never
downloads: it checks presence and prints the command to run.

## Verify it

```bash
raven models list      # reference, size, Ollama reachable, pulled, in use, this machine's numbers
raven doctor           # the "Bundled Free Model" row, plus a note per warning
raven repl             # talk to it in a terminal
```

In the web UI: **Admin → the model card**. It shows the same state, switches the model on with a
background pull and a progress state, and reverts it. The API behind the card is
`GET`/`POST /api/admin/models/experimental` (admin role).

A running gateway picks up a written switch within 5 s: `ConfigWatcher` reloads the env file when its
mtime changes and refreshes `Settings`. No restart, no second process to keep in sync.

## What the switch writes

- `DEFAULT_MODEL=ollama/<the name Ollama answers under>` in the env file `Settings` obeys;
- `HERETIC_PREVIOUS_DEFAULT_MODEL=<the value it had before>`, which is what `disable` restores;
- nothing else in that file. Your API keys, comments, line endings and key order survive; a
  `WEB_SECRET_KEY` is generated once and never rotated by a re-run;
- `raven.json` and `opencode.json` are updated only in the keys `setup` owns, so channel tokens,
  providers, agents and MCP servers you added stay where they are. A config that is not plain JSON
  (ravencode also reads JSONC) is reported and left untouched.

The other tiers are not switched: if `MODEL_FAST`, `MODEL_BALANCED` or `MODEL_QUALITY` still name a
hosted provider, the switch says so by name. A free default model does not make the whole deployment
free — calls routed through those tiers keep spending credit.

## Revert

```bash
raven models disable-heretic
```

That restores the previous `DEFAULT_MODEL` and removes the bookmark. The weights stay in Ollama;
`ollama rm hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF:Q4_K_M` reclaims the
5.63 GB.

## Air-gapped import

Copy the GGUF onto the machine by hand, then:

```bash
ollama create deepseek-v4-heretic -f models/Modelfile.heretic
raven models enable-heretic --no-pull
```

The Modelfile sets `num_ctx`, `temperature` and `top_p` and deliberately has no `TEMPLATE` block —
Ollama reads the chat template from the GGUF metadata, and a hand-written one overrides it and can
break thinking and tool calls. The switch reads `/api/tags` and writes the name it finds there, so it
writes `ollama/deepseek-v4-heretic` for an imported file and the `hf.co/…` reference for a pulled one.

`HERETIC_REF` points the pull at a mirror of the same file. Pointing it at a *different* model is
allowed, and every surface then says that the 5.63 GB figure and the preflight describe the bundled
Q4_K_M, not your reference.

## Docker

```bash
# .env
DEFAULT_MODEL=ollama/hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF:Q4_K_M
```

```bash
docker compose --profile heretic up -d
```

The `heretic-init` service waits for Ollama and pulls the reference over its HTTP API; the `raven`
container reaches it at `http://ollama:11434`. `DEFAULT_MODEL` comes from your `.env` — compose
deliberately does not set it, because a value there would silently outrank what you configured.

## When it does not work

| Symptom | Cause and fix |
|---|---|
| `host cannot run this model: …` | The preflight numbers above. Free the RAM or the disk, use a machine with more of it, or `--force` and accept paging |
| `Ollama not reachable at …` | Start it (`ollama serve`) or fix `OLLAMA_BASE_URL` |
| The switch writes, but the next start uses the old model | A `DEFAULT_MODEL` exported in the shell beats every env file — pydantic-settings applies the process environment last. `raven doctor` and the Admin card name the value; clear it where it is exported |
| The edit went to the wrong `.env` | The candidates are the install root's `.env`, `~/.raven/.env`, then `./.env`; the last one that exists wins. Both surfaces print the file they wrote |
| Windows blocks `Raven.exe` | Smart App Control in enforcement mode blocks an unsigned build, and self-signing does not satisfy it. Run `python -m raven` from source; turning Smart App Control off is irreversible, so it is your call, not the installer's |
| Every HTTP client raises `Invalid port ':1]'` | A `NO_PROXY=localhost,[::1]` in the environment. The config layer sanitizes the brackets at import; make sure you are running the current code |

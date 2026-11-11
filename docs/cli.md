---
description: "Reference for the raven command tree: start, status, doctor, deploy, agent, backup, models and the coding agent CLI."
---

# CLI Reference

_by [@ssrjkk](https://github.com/ssrjkk)_

## Usage

```bash
raven [OPTIONS] COMMAND [ARGS]...
```

## Commands

### `raven start`

Start the Raven AI gateway.

```bash
raven start [--daemon] [--port PORT] [--stateless]
```

### `raven stop`

Stop the running gateway.

### `raven status`

Show channel, agent, and plugin status.

### `raven onboard`

Interactive setup wizard.

### `raven init`

Generate a `raven.json` project scaffold.

### `raven setup`

Build the completely free, offline stack: Ollama, the model this machine can run, and the three
configuration files.

```bash
raven setup --free [--model NAME] [--experimental] [--yes]
```

The model is picked from measured hardware — `GlobalMemoryStatusEx` for RAM, `nvidia-smi` for VRAM and
`shutil.disk_usage` for the volume the weights land on (`raven/core/hardware.py`; `wmic` was removed
from Windows 11 24H2 and answers zero, so nothing here uses it). `--free` writes `raven.json`,
`opencode.json` and `.env`, updating the keys it owns and leaving the operator's own sections and API
keys in place. `--model NAME` overrides the pick. `--experimental` selects the bundled free model
below and asks before downloading its 5.63 GB; without a terminal it does not download and configures
the auto-picked model instead, so the switch is never written for weights that are not on the box.
`--yes` accepts the download for scripted runs.

### `raven deploy`

Generate a docker-compose file (minimal/full).

### `raven doctor`

Diagnose configuration and dependencies.

### `raven repl`

Launch the interactive agent REPL.

### `raven agent`

Send a message to the AI agent.

```bash
raven agent --message "Hello" [--agent AGENT_ID] [--channel CHANNEL]
```

### `raven history <session_id>`

View session message history.

### `raven pairing`

Manage user pairing codes.

```bash
raven pairing list
raven pairing approve <code>
```

### `raven service`

Manage the platform-native service.

```bash
raven service install|start|stop|status|remove|restart
```

`install` writes the backend for the platform it runs on and starts the service automatically:

| Platform | What `install` does |
| --- | --- |
| Windows | Registers the service `RavenAI` ("Raven AI Gateway") as a `pywin32` service with automatic start. Needs the `service-win` extra (`pip install "raven[service-win]"`) and an elevated shell; `install` exits non-zero if either is missing. |
| Linux | Writes `/etc/systemd/system/raven.service`, then `daemon-reload`, `enable` and `start`. Needs root, e.g. `sudo raven service install`. |
| macOS | Writes `~/Library/LaunchAgents/com.raven.ai.plist` and loads it with `launchctl`. |

`stop` asks the gateway to shut down through its own stop event, so channels, engines and the
database close instead of being cut off. It waits up to 40 s before reporting a stuck shutdown.

### `raven security`

Run security operations.

```bash
raven security audit [--deep]
```

### `raven tui`

Launch the Textual TUI dashboard.

### `raven models`

```bash
raven models list
raven models enable-heretic [--base-url URL] [--yes] [--no-pull] [--force]
raven models disable-heretic
```

`list` shows every configured provider and the state of the bundled free experimental model: its
reference, the weight size, whether Ollama is reachable, whether the weights are pulled, whether
`DEFAULT_MODEL` points at it, and what this machine measured.

`enable-heretic` pulls `hf.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF:Q4_K_M`
(5.63 GB, apache-2.0) into Ollama and writes `DEFAULT_MODEL` into the env file the gateway reads; a
running gateway reloads it within 5 s, so no restart is needed. It refuses when the hardware preflight
says this box cannot run it — that answer is in numbers (free disk, total and free RAM, VRAM available
to offload to) — and `--force` overrides. `--no-pull` only writes the switch, for a box where the
weights already exist. Without `--yes` the download is confirmed on a terminal and refused on a pipe.
`disable-heretic` puts back the value `DEFAULT_MODEL` had before, read from
`HERETIC_PREVIOUS_DEFAULT_MODEL`. The same switch is a card on the Admin screen, and `raven doctor`
reports it as `Bundled Free Model`. Hardware thresholds, the air-gapped import and the failure modes
are on one page: [Free Offline Model](local-models.md).

### `raven plugins list`

List loaded plugins.

### `raven task`

Task engine management.

```bash
raven task list|show|run|cancel|retry|logs
```

### `raven monitor`

Active monitoring management.

```bash
raven monitor list|add|remove|pause|resume|logs
```

### `raven routine`

Routine/cron management.

```bash
raven routine list|add|remove|pause|resume|logs
```

### `raven code`

Coding assistant (RavenCode).

```bash
raven code index|search|review|start|status|end
```

### `raven db`

Database management.

```bash
raven db migrate|backup|version
```

### `raven message send`

Send a message to a channel/user.

```bash
raven message send --channel <id> --user <id> --text "Message"
```

### `raven aios`

AI Gateway bridge.

```bash
python -m raven aios gateway
```

## RavenCode CLI

The coding agent installs its own entry point.

```bash
ravencode COMMAND [ARGS]...
```

### `ravencode tui`

Interactive agent session. Slash commands inside the prompt: `/ask`, `/plan`, `/code`,
`/debug`, `/agent <name> <task>`, `/undo`, `/redo`, `/checkpoint save|list|restore <id>`,
`/save [path]`, `/load [path]`, `/history`, `/mcp`, `/help`, `/exit`.

### `ravencode serve`

OpenAI-compatible HTTP API: `POST /v1/chat/completions` (streaming and non-streaming) and
`GET /v1/models`. The agent runs tools, so this endpoint executes code and shell commands —
it refuses to bind a non-loopback host unless authentication is configured.

```bash
ravencode serve --host 127.0.0.1 --port 8080
ravencode serve --host 0.0.0.0 --password <pw>      # or RAVENCODE_SERVER_PASSWORD
```

`--username` defaults to `ravencode`. `RAVENCODE_API_KEY` adds Bearer-token auth; both
credentials are compared in constant time. `RAVENCODE_SERVER_USERNAME` supplies the
username from the environment when `--username` is absent (`ravencode/api/server.py`).


Task routing inside `ravencode` can be made deterministic without a model: set
`RAVEN_SMART_ROUTING=0` and the live classification call is skipped, so a task runs on the
profile you named rather than the one the router would have chosen
(`ravencode/agents/orchestrator.py`). The same binary honours `RAVENCODE_MODEL`,
`RAVENCODE_TEMPERATURE`, `RAVENCODE_MAX_STEPS`, `RAVENCODE_THEME` and
`RAVENCODE_CONFIG_CONTENT`, listed in `.env.example`.
Request parameters follow the OpenAI protocol: `max_tokens` (1–200000) bounds the completion
and reports `finish_reason: "length"` when it cuts the answer short; `temperature` (0–2) is
accepted for client compatibility, while sampling itself is configured per provider in
`ravencode.json`.

### `ravencode session`

```bash
ravencode session list [--dir DIR]          # default: sessions under the data dir
ravencode session resume <id>            # reopen in the TUI with history intact
ravencode session export <id> [--sanitize] [-o out.json]
ravencode session import <file-or-url>   # URLs pass the SSRF guard (no internal addresses)
ravencode session delete <id>
```

Session ids are limited to `[A-Za-z0-9_-]{1,128}`: they become file names, so an id containing
a path separator is rejected instead of addressing a file outside the sessions directory. The
same rule guards the gateway and REST session stores.

`--sanitize` replaces anything that looks like a credential: keys named api_key/token/secret/

The memory counterpart is `raven backup export --sanitize`. Both flags call the same definition (`raven/core/security/credential_masker.py`), and `raven backup restore` refuses a file written with it, because restoring masked values would overwrite real memory with `***`.
password/credential/authorization (in any nesting, lists and header dicts included), plus
secret shapes found inside message text (`sk-…`, `ghp_…`, `AIza…`, `xox…`, `AKIA…`, `npm_…`,
`Bearer …`, PEM private-key headers). Ordinary words such as `tokenizer` or `monkey` are kept.

### `ravencode auth`

```bash
ravencode auth login --provider openrouter [--key sk-...] [--base-url URL]
ravencode auth list
ravencode auth logout [provider]
```

Provider keys live in `~/.config/ravencode/auth.json`, written with mode `0600`.

### `ravencode models` and `ravencode upgrade`

`models [--verbose]` lists providers and models from `ravencode.json` / `opencode.json`.
`upgrade [--version X.Y.Z]` re-installs the published `raven-agent` distribution.

### `ravencode integrations`

```bash
ravencode integrations github install [--force]   # writes .github/workflows/ravencode.yml
ravencode integrations github webhook --port 8080 [--host H] [--secret S]
ravencode integrations github run [--event-name E] [--payload BASE64] [--token T]
ravencode integrations gitlab install [--force]   # writes .gitlab-ci-ravencode.yml
ravencode integrations gitlab run [--token T] [--api-url URL]
```

`run` is what the installed CI templates invoke. Without flags it reads
`RAVENCODE_GITHUB_EVENT` (base64 JSON), `RAVENCODE_GITHUB_EVENT_NAME` and `GITHUB_TOKEN`;
GitLab uses `RAVENCODE_GITLAB_EVENT` and `GITLAB_TOKEN`.

## Global

```bash
raven --help                # top-level help
raven <command> --help      # command help
```

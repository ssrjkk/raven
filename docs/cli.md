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

### `raven security`

Run security operations.

```bash
raven security audit [--deep]
```

### `raven tui`

Launch the Textual TUI dashboard.

### `raven models list`

List configured LLM models.

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
credentials are compared in constant time.

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

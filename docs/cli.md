# CLI Reference

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

## Global

```bash
raven --help                # top-level help
raven <command> --help      # command help
```

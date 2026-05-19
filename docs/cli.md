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

### `raven doctor`

Diagnose configuration and dependencies.

### `raven agent`

Send a message to the AI agent.

```bash
raven agent --message "Hello" [--agent AGENT_ID] [--channel CHANNEL]
```

### `raven send`

Send a message to a session.

```bash
raven send --session SESSION_ID --text "Message"
```

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
raven security audit
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

Coding assistant.

```bash
raven code index|search|review|start|status|end
```

### `raven db`

Database management.

```bash
raven db migrate|backup|version
```

### `raven update`

Check for updates.

```bash
raven update [--dry-run]
```

### `raven history <session_id>`

View session message history.

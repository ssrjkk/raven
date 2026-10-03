# MCP integration

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven ships two MCP (Model Context Protocol) servers that any MCP client can connect to:
Claude Desktop, Qoder, opencode, Cursor, Windsurf, Cline, and others.

- **`raven-mcp`** — the Raven gateway tools (66 tools: files, shell, git, web, memory, routines, monitors, canvas, and more).
- **`ravencode-mcp`** — the same tool set in coding-agent mode.

Both speak JSON-RPC 2.0 over stdio, the transport every MCP client supports out of the box.

## What the servers expose

| Method | Behavior |
|--------|----------|
| `initialize` | Handshake; reports protocol `2025-03-26`, server name `raven-mcp` / `ravencode` |
| `notifications/initialized` | Acknowledged silently (no response, per JSON-RPC) |
| `ping`, `logging/setLevel` | Answered with an empty result |
| `tools/list` | All 66 tools as `{name, description, inputSchema}` |
| `tools/call` | Executes the tool and returns `{content: [{type: "text", text: ...}]}` |

## Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "raven": {
      "command": "raven-mcp",
      "args": ["--workspace", "C:\\path\\to\\your\\project"]
    }
  }
}
```

Restart Claude Desktop. Raven's tools appear under the tools (wrench) menu.

## Qoder

Add to the MCP servers list in Qoder settings (or `.qoder/mcp.json` in the project):

```json
{
  "mcpServers": {
    "raven": {
      "command": "raven-mcp",
      "args": ["--workspace", "/path/to/your/project"]
    }
  }
}
```

## opencode

Add to `opencode.json`:

```json
{
  "mcp": {
    "raven": {
      "type": "local",
      "command": ["raven-mcp", "--workspace", "/path/to/your/project"]
    }
  }
}
```

## Cursor / Windsurf / Cline

Same shape as Claude Desktop — a stdio server entry:

```json
{
  "mcpServers": {
    "raven": {
      "command": "raven-mcp",
      "args": ["--workspace", "/path/to/your/project"]
    }
  }
}
```

## Without installing (uvx-style)

If you don't want to install the package globally, point the client at the module entry point:

```json
{
  "mcpServers": {
    "raven": {
      "command": "python",
      "args": ["-m", "raven.core.mcp", "--workspace", "/path/to/project"]
    }
  }
}
```

The `ravencode.mcp` module works identically (`python -m ravencode.mcp`).

## Workspace isolation

The `--workspace` argument is the only directory tools may touch — it defaults to the
current directory. Absolute paths outside it (and symlink escapes) are rejected with a
permission error. Pass `--workspace D:\my-project` (or the POSIX equivalent) to scope
each client to its own project.

## HTTP transport (advanced)

The gateway also exposes the same protocol over HTTP when `raven start` is running:

| Endpoint | Description |
|----------|-------------|
| `POST /mcp/rpc` | Any JSON-RPC MCP call (initialize, tools/list, tools/call) |
| `GET /mcp/tools` | Tool list in plain JSON |
| `POST /mcp/tools/{name}` | Direct tool call with `{"arguments": {...}}` |
| `GET /mcp/health` | Liveness probe |
| `GET /mcp/events` | Server-sent events stream |

HTTP access requires a token: pass your `web_secret_key` as `X-Raven-Key: <key>` or
`Authorization: Bearer <token>`. A minimal remote-client config:

```json
{
  "mcpServers": {
    "raven": {
      "url": "http://your-server:18888/mcp/rpc",
      "headers": {"X-Raven-Key": "your-key"}
    }
  }
}
```

## Smoke test

After installing, verify the stdio server locally:

```bash
python scripts/mcp_smoke.py
```

Expected output: `initialize` succeeds, `tools/list` returns 66 tools with
`name`/`description`/`inputSchema` keys, a `read` call returns file content, and a
path outside the workspace returns `[execution_error] tool failed`.

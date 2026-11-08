---
description: "What raven-mcp and ravencode-mcp expose over stdio and HTTP, and how to add them to Claude Desktop, Qoder, opencode or Cursor."
---

# MCP integration

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven ships two MCP (Model Context Protocol) servers that any MCP client can connect to:
Claude Desktop, Qoder, opencode, Cursor, Windsurf, Cline, and others.

- **`raven-mcp`** — the Raven gateway tools (66 tools: files, shell, git, web, memory, routines, monitors, canvas, and more).
- **`ravencode-mcp`** — the same tool set in coding-agent mode.

Both speak JSON-RPC 2.0 over stdio — one UTF-8 JSON object per line, the encoding the servers
pin for themselves rather than inheriting the machine's code page. A blank line between messages
is framing and is skipped, a line that is not JSON is answered with `-32700`, and a JSON value
that is not an object with `-32600`; none of them end the session.

## What the servers expose

| Method | Behavior |
|--------|----------|
| `initialize` | Handshake; reports protocol `2025-03-26`, server name `raven-mcp` / `ravencode` |
| `notifications/initialized` | Acknowledged silently (no response, per JSON-RPC) |
| `ping`, `logging/setLevel` | Answered with an empty result |
| `tools/list` | All 66 tools as `{name, description, inputSchema, annotations}` - the hints come from the same table the execution policy reads, so `destructiveHint` is true for exactly the 28 tools a call is gated on and `openWorldHint` for the 15 that leave the machine |
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

## What the MCP surface enforces

A client that can reach the server can call any tool the operator has not refused. Three
settings apply to MCP exactly as they do to the agent inside the gateway, and both come from
the same builder (`raven/core/security/tool_policy.py:policy_from_settings`):

- `TOOLS_DENY` / `TOOLS_ALLOW` - the deny list is applied by default, and `TOOLS_ALLOW`
  restricts the surface to the names it lists;
  Of the 66 tools served here the default `TOOLS_DENY` touches exactly one, `nodes_list`;
  the rest of that list names gateway tools this registry does not serve.
- `EXEC_SECURITY` / `EXEC_ASK` - the 8 exec-class tools (`git_commit` and the seven
  `browser_*`) follow it, so with the default `EXEC_SECURITY=deny` an MCP client cannot run
  them either;
Path containment is not duplicated here: these tools are confined by
`ravencode/runtime/workspace.py:confine` against the root the server was given with
`--workspace` (or `RAVEN_WORKSPACE`), which is a different root from the gateway's
`WORKSPACE_PATH`; a path outside it raises `PermissionError` inside the tool.

A refused call answers `[denied] ...` with `isError: true` over JSON-RPC and HTTP 403 on
`POST /mcp/tools/{name}`. The one thing MCP does not inherit is `TOOLS_PROFILE`: the named
profiles list plugin tool names (`files.read`, `api.http_get`), this registry serves `read`
and `http_get`, and an allow-list of names that can never match reads as a blanket refuse.
 The orchestrator builds the same policy with `profile="full"` for the same reason.

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
`name`/`description`/`inputSchema`/`annotations` keys, a `read` call returns file
content, and a
path outside the workspace returns `[execution_error] tool failed`.

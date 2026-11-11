---
description: "Writing a plugin: the two stacks, their contracts, where each is read from, and how a plugin registers tools Raven will run."
---

# Plugin Development Guide

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven runs two plugin stacks, and a plugin written for one does not load in the other:

| | bundled | user |
|---|---|---|
| Code lives in | `raven/plugins/`, inside the package | a directory the resolver lists, e.g. `plugins/` |
| Trust | shipped by you, so it runs in-process | untrusted, so it runs in its own interpreter |
| Contract | `async def` tools in `plugin.py`, published automatically | `register(ctx) -> Plugin`, declaring each tool |
| Reported by | `raven plugins list`, `raven plugins info` | `raven doctor` → *User Plugins* |

The tracked `plugins/example-http/plugin.py` is the working user-plugin example.

## Quick Start

A bundled plugin (goes into `raven/plugins/`):

```
raven/plugins/my_plugin/
├── __init__.py      (empty)
└── plugin.py        (your async tools)
```

A user plugin (goes into a directory [Loading Plugins](#loading-plugins) lists — `raven setup` creates
`plugins/` at the project root):

```
plugins/my_plugin/
└── plugin.py        (register(ctx) -> Plugin)
```

## Writing a bundled plugin

### What becomes a tool

Only a coroutine **defined in that `plugin.py`, under its own name** is published:

- imported coroutines are skipped, so a helper you brought in from another module does not appear as a second tool with a name nobody wrote down
- aliases are skipped, for the same reason (`fetch = browse` publishes nothing new)
- names starting with `_` are skipped
- ordinary (non-`async`) functions are never published — that is how you keep a host-side hook, such as a callback registrar that needs a real Python object, out of the tool surface

Function parameters become the tool's JSON schema from the type hints. A `*args` or `**kwargs` slot stays listed but is never required: a JSON tool call cannot fill it by name.

```python
"""Weather plugin for Raven AI."""

async def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    city: City name (e.g. "London")
    units (str): Temperature units — celsius or fahrenheit.
        A description may continue on the next, more indented line.
    """
    return f"Weather in {city}: 22°{units[0].upper()}"
```

The function name becomes the tool name, prefixed with the plugin directory (`my_plugin.get_weather`).

### Descriptions

The first line of the docstring is the description the model sees. **Without a docstring it is the bare function name** (`get_weather`), which tells the model nothing; the loader logs a `WARNING` naming the tool so this is visible at startup, and `tests/test_plugin_surface_integrity.py` fails if a shipped tool is left that way.

Each parameter is described by a line that starts with its name:

```
name: text
name (type): text
```

The text continues on the following more-indented lines until a blank line or a section header such as `Args:` or `Returns:`. A prose sentence that merely happens to begin with the parameter word is not read as a description, so write the colon.

## Supported Types

Python type → JSON schema mapping:

| Python Type | JSON Schema |
|-------------|-------------|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list[str]` | `{"type": "array", "items": {"type": "string"}}` |
| `dict[str, Any]` | `{"type": "object"}` |
| `Optional[str]` | `{"type": "string"}` (not required) |

## Best Practices

1. **Always add a docstring** — the first line is the tool description; without it the model sees only the bare function name (see [Descriptions](#descriptions))
2. **Describe each parameter on its own line** — `name: text`; the schema field is otherwise empty
3. **Use descriptive parameter names** — the LLM uses them to understand what to pass
4. **Return strings** — tool results are displayed to the LLM as text
5. **Handle errors gracefully** — return error messages instead of raising exceptions
6. **Say what the tool actually does** — a description that promises delivery, persistence or a schedule the code does not perform is a bug, not a flavour of wording
7. **Keep functions focused** — one tool, one responsibility

## Writing a user plugin (sandboxed)

A user plugin exports `register()`. It runs in a separate interpreter, so nothing is shared with the
gateway process except JSON over a pipe — which is why the tools are declared rather than inferred:

```python
from ravencode.runtime.plugins import Plugin


def register(ctx=None) -> Plugin:
    async def get_weather(city: str) -> str:
        body = await ctx.safe_http("GET", f"https://wttr.in/{city}")
        return body[:500]

    return Plugin(
        name="weather",
        version="0.1.0",
        tools={
            "get_weather": {
                "name": "get_weather",
                "description": "Fetch a one-line forecast for a city from wttr.in.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "City name"}},
                    "required": ["city"],
                },
                "dangerous": False,
                "handler": get_weather,
            }
        },
    )
```

- **The tool name the model sees is namespaced by the directory** — `plugins/weather/` publishes
  `weather.get_weather`. Two plugins can therefore ship a `get_weather` without colliding, and an
  operator can deny one plugin's tool without denying every plugin's.
- **`parameters` is the JSON schema you write**, not something derived from the signature; the type-hint
  mapping under [Supported Types](#supported-types) belongs to the bundled loader.
- **`dangerous: true` puts the tool on the confirmation path.** Separately, a tool whose name contains
  one of the exec-class tokens (`http_post`, `shell`, `python`, `db_query`, `git_push`, …) is gated by
  `EXEC_SECURITY` whatever this flag says, because the name is what the policy matches.
- **`ctx` is the only door to the outside.** `ctx.safe_http(method, url, headers=…, body=…)`,
  `ctx.safe_file_read(path)` and `ctx.safe_file_write(path, content)` ask the host, which answers them
  through the same checks as the built-in tools: `safe_http` validates the URL against the SSRF rules and
  serves only `GET` and `POST`, and the two file calls go through the workspace-containment path. `ctx`
  is `None` when a plugin is loaded in-process instead of sandboxed.
- **What the sandbox refuses.** Only these modules import: `__future__`, `base64`, `binascii`,
  `collections`, `dataclasses`, `datetime`, `decimal`, `enum`, `functools`, `hashlib`, `hmac`,
  `itertools`, `json`, `math`, `ravencode.runtime.plugins`, `re`, `statistics`, `string`, `textwrap`,
  `time`, `typing`, `unicodedata`, `uuid`, `urllib.parse`, `zoneinfo`. Relative imports are blocked
  outright. Builtins are an allowlist: `open`, `exec`, `eval`, `compile`, `input` and `getattr` are
  absent, and `__import__` exists only to enforce the module list above — which is also why the plugin
  can name `Plugin`. `from ravencode.runtime.plugins import Plugin` gives you a stand-in class defined
  inside the worker, not the host module: the host module's namespace held `Path` and `asyncio`, and
  `Plugin.__init__.__globals__` was a route to them.
- **What the boundary is, exactly.** It stops a plugin that reaches for a socket, a file or a process
  by accident, and it routes every deliberate one through a host-side check the operator can read. It is
  not a hostile-code container: no builtins allowlist stops an interpreter that walks
  `object.__subclasses__()`, so the child is also built to hold nothing worth taking. It starts with 15
  environment variables instead of the parent's 107 and none named like a credential, and the Raven
  checkout is kept off its `PYTHONPATH`, so there is no `raven` package to import for the settings the
  `.env` file backs. A plugin that escapes the sandbox still lands in a process holding no secrets of
  its own; it can then only do what the account it runs under can already do. Treat a third-party plugin
  as software you are installing, and read it first.
- **`register()` gets 2 seconds.** A plugin whose `register()` blocks or raises is logged and skipped;
  the agent still starts, without that plugin.

## Skills

Skills are plugins with a `SKILL.md` file that adds context to the system prompt:

```
plugins/morning_briefing/
├── __init__.py
├── plugin.py
└── SKILL.md
```

The `SKILL.md` content is injected into the agent's system prompt when the skill is activated.

## Loading Plugins

Bundled plugins load in-process when the gateway starts, from `raven/plugins/` inside the package. That
directory is fixed; `raven plugins list` and `raven plugins info` report on it.

User plugins are read from every directory the artifact resolver lists for the `plugins` kind, first
match wins per plugin directory name:

1. `PLUGINS_DIR`, then `RAVEN_PLUGINS_DIR` — a comma- or semicolon-separated list
2. `paths.plugins` in `raven.json` (`RAVEN_CONFIG` first, else `./raven.json`)
3. `.raven.local/plugins` and `.raven/plugins` in the current directory
4. `~/.config/raven/plugins`
5. the legacy `plugins/` next to the checkout

`raven setup` creates `plugins/` in the project and writes that entry into `paths.plugins`; `raven doctor`
prints the resolved list under *User Plugins*, so the answer comes from the machine rather than from this
page. There is no `plugins_dir` key — a second name for the same setting is how an operator ends up with
two answers.

A long-lived process registers user plugins at startup and hot-reloads them while it runs (touch a
`plugin.py` and that one plugin reloads). The surfaces that do this: `raven start` (the Raven gateway)
and `raven aios gateway` (which is what the web SPA and the extension talk to), the aios bridge
WebSocket, `raven flow serve`, `raven code` (including `--parallel`), and the ravencode TUI and its
HTTP server. Registration is once per event loop, because a plugin worker's pipes belong to the loop
that started it: a surface that starts on a fresh loop finds the old worker unreachable, drops it and
starts one it can talk to. What still cannot work is registering in one `asyncio.run` and calling the
tool in the next — the call reaches a worker whose loop is already closed — which is why short-lived
commands wrap their one flow in `running_plugin_tools()`.

Two things this cannot do:

- **A packaged `.exe` cannot load user plugins.** The sandbox is a second interpreter launch, and in a
  frozen build `sys.executable` is Raven itself, so spawning it would start a second Raven instead of a
  sandbox. The worker refuses with that reason in the log. Bundled plugins are unaffected.
- **A plugin is never loaded in the middle of a model call.** If `raven doctor` lists your plugin
  directory but the tool is missing, the surface you are using started before the file existed — restart
  it. The tool surface warns in the log, naming every plugin on disk that it was never handed.

## Testing

A bundled plugin, called through the loader that the gateway uses:

```python
from pathlib import Path

from raven.core.plugin_loader import PluginLoader

loader = PluginLoader()
loader.load_from_dir(Path("raven/plugins/my_plugin"))
tool = loader.get_tool("my_plugin.get_weather")
print(await tool.handler(city="London"))
```

A user plugin, through the same sandbox the agent reaches it through — this spawns the real worker, so
the import allowlist and the capability round-trip are what actually bite:

```python
import asyncio
from pathlib import Path

from ravencode.runtime.plugins import discover_plugins

plugins = asyncio.run(discover_plugins(Path("plugins")))
tool = plugins[0].tools["my_plugin.get_weather"]
print(asyncio.run(tool["handler"](city="London")))
```

Nothing about a user plugin is mocked in `tests/test_ravencode_runtime_plugins.py`: registration, the
namespaced name, a capability round-trip and a sandbox refusal all run against a real interpreter.

## Example: File Search Plugin

This one is a **bundled** plugin — it imports `pathlib`, which a sandboxed user plugin cannot do. Put it
in `raven/plugins/file_search/`.

```python
"""File search plugin for Raven AI."""
from pathlib import Path


async def search_files(pattern: str, directory: str = ".") -> str:
    """Search for files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. "*.py", "**/*.md")
        directory: Directory to search in
    """
    matches = list(Path(directory).rglob(pattern))
    if not matches:
        return "No files found."
    results = [str(m.relative_to(directory)) for m in matches[:50]]
    return "\n".join(results)


async def read_file(path: str) -> str:
    """Read contents of a file.

    Args:
        path: Path to the file
    """
    p = Path(path)
    if not p.exists():
        return f"File not found: {path}"
    return p.read_text(encoding="utf-8", errors="replace")[:10000]
```

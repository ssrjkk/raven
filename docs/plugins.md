---
description: "Writing a plugin: the supported types, the manifest, skills, and how a plugin registers tools the gateway will run."
---

# Plugin Development Guide

_by [@ssrjkk](https://github.com/ssrjkk)_

Raven AI supports a plugin system that allows you to extend the agent's capabilities with custom tools.

## Quick Start

Create a new plugin directory:

```
plugins/my_plugin/
├── __init__.py      (empty)
└── plugin.py        (your tools)
```

## Writing a Plugin

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

Plugins are loaded automatically from the directory specified in your config:

```json
{
  "plugins_dir": "plugins"
}
```

Or manually via the CLI:

```bash
raven plugins list
```

## Testing

Test your plugin by calling the tool directly:

```python
from raven.core.plugin_loader import PluginLoader
loader = PluginLoader()
loader.load_from_dir("plugins/my_plugin")
tool = loader.get_tool("get_weather")
result = await tool.handler(city="London")
print(result)
```

## Example: File Search Plugin

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

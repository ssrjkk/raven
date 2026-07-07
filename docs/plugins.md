# Plugin Development Guide

Raven AI supports a plugin system that allows you to extend the agent's capabilities with custom tools.

## Quick Start

Create a new plugin directory:

```
plugins/my_plugin/
├── __init__.py      (empty)
└── plugin.py        (your tools)
```

## Writing a Plugin

Each `async` function in `plugin.py` becomes a tool the agent can call. Function parameters become the tool's JSON schema using Python type hints.

```python
"""Weather plugin for Raven AI."""

async def get_weather(city: str, units: str = "celsius") -> str:
    """Get current weather for a city.

    Args:
        city: City name (e.g. "London")
        units: Temperature units — celsius or fahrenheit
    """
    # Your logic here
    return f"Weather in {city}: 22°{units[0].upper()}"
```

The function name becomes the tool name (`get_weather`), the docstring becomes the description, and type hints become parameter schema.

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

1. **Always add a docstring** — it becomes the tool description shown to the LLM
2. **Use descriptive parameter names** — the LLM uses them to understand what to pass
3. **Return strings** — tool results are displayed to the LLM as text
4. **Handle errors gracefully** — return error messages instead of raising exceptions
5. **Keep functions focused** — one tool, one responsibility

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

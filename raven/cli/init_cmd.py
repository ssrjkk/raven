from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from raven.core.config import settings
from raven.core.logging import setup_logging

console = Console()

CONFIG_STORE_VERSION = "0.4.0"

RAVEN_JSON_TEMPLATE = """\
{
  "version": "0.4.0",
  "llm": {
    "provider": "{provider}",
    "default_model": "{default_model}",
    "api_key": "{{RAVEN_{provider_upper}_API_KEY}}"
  },
  "channels": {channels},
  "security": {{
    "dm_policy": "{dm_policy}",
    "web_port": {web_port}
  }},
  "workspace": "workspace",
  "plugins_dir": "plugins",
  "skills_dir": "workspace/skills",
  "paths": {{
    "skills": ["workspace/skills"],
    "commands": [".raven/commands"],
    "rules": [".raven/rules"],
    "agents": [".raven/agents"],
    "plugins": ["plugins"],
    "hooks": [".raven/hooks"]
  }}
}
"""

ENV_EXAMPLE_TEMPLATE = """\
# Raven AI Configuration
# Copy this file to .env and fill in your values.

# LLM Provider
# Choose one: OPENROUTER, ANTHROPIC, OPENAI, OLLAMA
RAVEN_LLM_PROVIDER={provider}

# API Keys (required for cloud providers)
{api_key_lines}

# Default model to use
RAVEN_DEFAULT_MODEL={default_model}

# Channels (optional — uncomment to enable)
{channel_lines}

# Security
{security_lines}

# Paths
# RAVEN_WORKSPACE=workspace
# RAVEN_PLUGINS_DIR=plugins
# RAVEN_SKILLS_DIR=workspace/skills
# RAVEN_COMMANDS_DIR=.raven/commands
# RAVEN_RULES_DIR=.raven/rules
# RAVEN_AGENTS_DIR=.raven/agents
# RAVEN_HOOKS_DIR=.raven/hooks

# Web UI
# RAVEN_WEB_PORT={web_port}
# RAVEN_WEB_SECRET_KEY=

# Logging
# RAVEN_LOG_LEVEL=INFO

# Monitoring
# RAVEN_MONITOR_DB_PATH=data/monitors.db

# Rate Limiting
# RAVEN_CHANNEL_RATE_LIMIT=10
# RAVEN_USER_RATE_LIMIT=5

# DM Policy: open, closed, pairing
# RAVEN_DM_POLICY=pairing
"""


def _provider_upper(p: str) -> str:
    return p.upper()


def _prompt_llm() -> dict[str, str]:
    console.print(Rule(style="bold blue"))
    console.print(Panel.fit("[bold]LLM Provider[/bold]", border_style="blue"))
    console.print(
        "Choose your primary AI model provider.\n"
        "[bold]OpenRouter[/bold] — 200+ models with one key\n"
        "[bold]Anthropic[/bold] — Claude only\n"
        "[bold]OpenAI[/bold] — GPT-4o / GPT-4o-mini\n"
        "[bold]Ollama[/bold] — Local (no API key needed)"
    )
    provider = Prompt.ask("Provider", choices=["openrouter", "anthropic", "openai", "ollama"], default="openrouter")
    cfg: dict[str, str] = {"provider": provider}

    if provider == "openrouter":
        key = Prompt.ask("OpenRouter API Key", password=True)
        cfg["api_key"] = key
        cfg["default_model"] = Prompt.ask("Default model", default="openrouter/google/gemini-2.0-flash-001")
    elif provider == "anthropic":
        key = Prompt.ask("Anthropic API Key", password=True)
        cfg["api_key"] = key
        cfg["default_model"] = "claude-sonnet-4-20250514"
    elif provider == "openai":
        key = Prompt.ask("OpenAI API Key", password=True)
        cfg["api_key"] = key
        cfg["default_model"] = "gpt-4o"
    elif provider == "ollama":
        url = Prompt.ask("Ollama base URL", default=settings.ollama_base_url)
        cfg["ollama_url"] = url
        cfg["default_model"] = Prompt.ask("Model name", default="llama3")

    return cfg


def _prompt_channels() -> dict[str, Any]:
    console.print(Rule(style="bold green"))
    console.print(Panel.fit("[bold]Channels[/bold]", border_style="green"))
    channels: dict[str, Any] = {}
    channels["telegram"] = {"enabled": Confirm.ask("Enable Telegram?", default=True)}
    if channels["telegram"]["enabled"]:
        channels["telegram"]["token"] = Prompt.ask("Telegram Bot Token", password=True)

    channels["discord"] = {"enabled": Confirm.ask("Enable Discord?", default=False)}
    if channels["discord"]["enabled"]:
        channels["discord"]["token"] = Prompt.ask("Discord Bot Token", password=True)

    channels["webchat"] = {"enabled": True, "auto_start": True}
    return channels


def _prompt_security() -> dict[str, Any]:
    console.print(Rule(style="bold red"))
    console.print(Panel.fit("[bold]Security[/bold]", border_style="red"))
    policy = Prompt.ask("DM policy", choices=["pairing", "open", "closed"], default="pairing")
    port_str = Prompt.ask("Web UI port", default="18888")
    try:
        port = int(port_str)
    except ValueError:
        port = settings.web_port
    return {"dm_policy": policy, "web_port": port}


def _show_summary(llm: dict[str, str], channels: dict[str, Any], security: dict[str, Any]) -> None:
    console.print(Rule(style="bold green"))
    console.print(Panel.fit("[bold green]Configuration Summary[/bold green]", border_style="green"))
    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_row("Provider", llm["provider"])
    table.add_row("Model", llm.get("default_model", ""))
    table.add_row("Telegram", "[OK]" if channels.get("telegram", {}).get("token") else "[NO]")
    table.add_row("Discord", "[OK]" if channels.get("discord", {}).get("token") else "[NO]")
    table.add_row("WebChat", "[OK]")
    table.add_row("DM Policy", security["dm_policy"])
    table.add_row("Web Port", str(security["web_port"]))
    console.print(table)


def _write_raven_json(llm: dict[str, str], channels: dict[str, Any], security: dict[str, Any], path: Path) -> None:
    channels_json = {}
    for cid, cfg in channels.items():
        channels_json[cid] = {"enabled": cfg["enabled"]}
    data = {
        "version": CONFIG_STORE_VERSION,
        "llm": {
            "provider": llm["provider"],
            "default_model": llm.get("default_model", ""),
            "api_key": llm.get("api_key", ""),
        },
        "channels": channels_json,
        "security": security,
        "workspace": "workspace",
        "plugins_dir": "plugins",
        "skills_dir": "workspace/skills",
        "paths": {
            "skills": ["workspace/skills"],
            "commands": [".raven/commands"],
            "rules": [".raven/rules"],
            "agents": [".raven/agents"],
            "plugins": ["plugins"],
            "hooks": [".raven/hooks"],
        },
    }
    path.write_text(json.dumps(data, indent=2))
    console.print(f"[green]Written {path}[/green]")


def _write_env_example(llm: dict[str, str], channels: dict[str, Any], security: dict[str, Any], path: Path) -> None:
    api_key_lines = ""
    provider_upper = llm["provider"].upper()
    if llm["provider"] == "ollama":
        api_key_lines = f"# RAVEN_OLLAMA_BASE_URL={llm.get('ollama_url', settings.ollama_base_url)}"
    else:
        api_key_lines = f"RAVEN_{provider_upper}_API_KEY={llm.get('api_key', '')}"

    channel_lines_parts = []
    for cid, cfg in channels.items():
        if cfg["enabled"]:
            token_var = f"RAVEN_{cid.upper()}_BOT_TOKEN"
            token_val = cfg.get("token", "")
            if token_val:
                channel_lines_parts.append(f"{token_var}={token_val}")
            else:
                channel_lines_parts.append(f"# {token_var}=your_token_here")
    channel_lines = "\n".join(channel_lines_parts)

    security_lines = "\n".join(
        [
            f"RAVEN_DM_POLICY={security['dm_policy']}",
            f"# RAVEN_WEB_PORT={security['web_port']}",
        ]
    )

    content = ENV_EXAMPLE_TEMPLATE.format(
        provider=llm["provider"],
        provider_upper=provider_upper,
        default_model=llm.get("default_model", ""),
        api_key_lines=api_key_lines,
        channel_lines=channel_lines,
        security_lines=security_lines,
        web_port=settings.web_port,
    )
    path.write_text(content)
    console.print(f"[green]Written {path}[/green]")


def init() -> None:
    console.print()
    console.print(Panel.fit("[bold cyan]raven init — Project Scaffolding[/bold cyan]", border_style="cyan"))
    console.print()
    setup_logging()

    root = Path.cwd()
    if (root / "raven.json").exists() and not Confirm.ask("raven.json already exists. Overwrite?", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return

    llm = _prompt_llm()
    channels = _prompt_channels()
    security = _prompt_security()

    _show_summary(llm, channels, security)
    if not Confirm.ask("Write configuration?", default=True):
        console.print("[yellow]Aborted.[/yellow]")
        return

    _write_raven_json(llm, channels, security, root / "raven.json")
    _write_env_example(llm, channels, security, root / ".env.example")

    (root / "workspace").mkdir(exist_ok=True)
    (root / "workspace" / "skills").mkdir(exist_ok=True)
    (root / "plugins").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)

    artifact_dirs = ("skills", "commands", "rules", "agents", "plugins", "hooks")
    team = root / ".raven"
    for sub in artifact_dirs:
        (team / sub).mkdir(parents=True, exist_ok=True)
    personal = root / ".raven.local"
    for sub in artifact_dirs:
        (personal / sub).mkdir(parents=True, exist_ok=True)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Project initialized![/bold green]\n\n"
            "Next steps:\n"
            "  Copy [bold].env.example[/bold] to [bold].env[/bold] and fill in your values\n"
            "  Run [bold]raven start[/bold] to launch Raven\n"
            "  Run [bold]raven doctor[/bold] to verify setup\n\n"
            "Files created:\n"
            f"  {root / 'raven.json'}\n"
            f"  {root / '.env.example'}\n"
            f"  {root / 'workspace/'}\n"
            f"  {root / 'plugins/'}\n"
            f"  {root / 'data/'}\n"
            f"  {root / '.raven/'}  (team artifacts)\n"
            f"  {root / '.raven.local/'}  (personal artifacts, gitignore it)",
            border_style="green",
        )
    )


PLUGIN_TEMPLATE = """\
from __future__ import annotations

from typing import Any

from raven.core.models import PluginTool


def get_tools() -> list[PluginTool]:
    \"\"\"Define your plugin's tools here.\"\"\"
    return []


def on_load() -> None:
    \"\"\"Called when the plugin is loaded.\"\"\"
    pass


def on_unload() -> None:
    \"\"\"Called when the plugin is unloaded.\"\"\"
    pass
"""


SKILL_TEMPLATE = """\
from __future__ import annotations

from typing import Any


async def my_skill(user_id: str, channel: str, **kwargs: Any) -> str:
    \"\"\"Implement your skill logic here.\"\"\"
    return f"Hello from my_skill, {user_id}!"


def get_metadata() -> dict[str, Any]:
    return {
        "name": "my_skill",
        "description": "A custom Raven skill",
    }
"""


def init_plugin_template() -> None:
    setup_logging()
    root = Path.cwd()
    name = Prompt.ask("Plugin name", default="my_plugin")
    target = root / "plugins" / name
    if target.exists() and not Confirm.ask(f"{target} exists. Overwrite?", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return
    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text(PLUGIN_TEMPLATE)
    (target / "README.md").write_text(f"# {name}\n\nRaven plugin.\n")
    console.print(f"[green]Plugin '{name}' scaffolded at {target}[/green]")


def init_skill_template() -> None:
    setup_logging()
    root = Path.cwd()
    name = Prompt.ask("Skill name", default="my_skill")
    skills_dir = root / "workspace" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    target = skills_dir / f"{name}.py"
    if target.exists() and not Confirm.ask(f"{target} exists. Overwrite?", default=False):
        console.print("[yellow]Aborted.[/yellow]")
        return
    target.write_text(SKILL_TEMPLATE)
    console.print(f"[green]Skill '{name}' scaffolded at {target}[/green]")

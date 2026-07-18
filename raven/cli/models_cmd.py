from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from raven.core.config import settings

console = Console()


@click.group(name="models")
def models_group():
    """List available models"""


@models_group.command("list")
def models_list():
    """List configured LLM models"""
    table = Table(title="Configured Models")
    table.add_column("Provider", style="cyan")
    table.add_column("Status")
    table.add_column("Default")
    table.add_row(
        "OpenRouter",
        "[OK]" if settings.openrouter_api_key.get_secret_value() else "[NO]",
        "✓" if settings.default_model.startswith("openrouter/") else "",
    )
    table.add_row(
        "Anthropic",
        "[OK]" if settings.anthropic_api_key.get_secret_value() else "[NO]",
        "✓" if settings.default_model.startswith("claude") else "",
    )
    table.add_row("OpenAI", "[OK]" if settings.openai_api_key.get_secret_value() else "[NO]", "")
    table.add_row(
        "Ollama",
        "[OK]" if settings.ollama_base_url else "[NO]",
        "✓" if settings.default_model.startswith("ollama/") else "",
    )
    console.print(table)
    console.print(f"\nDefault model: [bold]{settings.default_model}[/bold]")

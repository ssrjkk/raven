from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from raven.core.config import settings
from raven.core.heretic_model import HERETIC_SIZE_GB, disable, enable, status

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
        "Groq",
        "[OK]" if settings.groq_api_key.get_secret_value() else "[NO]",
        "✓" if settings.default_model.startswith("groq/") else "",
    )
    table.add_row(
        "Ollama",
        "[OK]" if settings.ollama_base_url else "[NO]",
        "✓" if settings.default_model.startswith("ollama/") else "",
    )
    console.print(table)
    console.print(f"\nDefault model: [bold]{settings.default_model}[/bold]")

    st = status(settings.ollama_base_url)
    exp = Table(title="Bundled free experimental model (Qwen3.5-9B, uncensored)")
    exp.add_column("Check", style="cyan")
    exp.add_column("Value")
    exp.add_row("Reference", st.ref)
    exp.add_row("Weights", f"{st.size_gb:.2f} GB ({st.ref.rsplit(':', 1)[-1]})")
    exp.add_row(
        "Ollama", "[OK] reachable" if st.ollama_reachable else f"[NO] not reachable at {settings.ollama_base_url}"
    )
    exp.add_row("In Ollama", "[OK] pulled" if st.present else "[NO] not pulled")
    exp.add_row("In use", "[OK] DEFAULT_MODEL" if st.is_default else f"[NO] DEFAULT_MODEL={st.default_model}")
    exp.add_row("This machine", st.hardware.summary())
    for blocker in st.blockers:
        exp.add_row("[red]blocked[/red]", blocker)
    for warning in st.warnings:
        exp.add_row("[yellow]note[/yellow]", warning)
    console.print(exp)
    if st.is_default:
        console.print(f"[dim]Configured in: {st.env_file}\nRevert: raven models disable-heretic[/dim]")
    else:
        console.print("[dim]Switch on: raven models enable-heretic[/dim]")


@models_group.command("enable-heretic")
@click.option("--base-url", default=None, help="Ollama base URL (default: OLLAMA_BASE_URL)")
@click.option("--yes", is_flag=True, help=f"Skip the prompt that confirms the {HERETIC_SIZE_GB:.2f} GB download")
@click.option("--no-pull", is_flag=True, help="Only point Raven at it; assume the weights are already in Ollama")
@click.option("--force", is_flag=True, help="Switch it on even when the hardware preflight refuses")
def models_enable_heretic(base_url: str | None, yes: bool, no_pull: bool, force: bool) -> None:
    """Switch Raven onto the bundled free experimental model, pulling it if missing."""
    url = base_url or settings.ollama_base_url
    st = status(url)
    console.print(f"[bold]{st.ref}[/bold] — {st.size_gb:.2f} GB\n{st.hardware.summary()}")
    for blocker in st.blockers:
        console.print(f"[red]blocked[/red] {blocker}")
    if not st.present and not no_pull and not yes:
        if not sys.stdin.isatty():
            console.print(
                f"[red]refusing to download {st.size_gb:.2f} GB non-interactively[/red] "
                f"(read the checks above, then re-run with --yes)"
            )
            raise SystemExit(1)
        click.confirm(f"Download {st.size_gb:.2f} GB into Ollama at {url}?", abort=True)
    result = enable(url, pull=not no_pull, force=force)
    for warning in result.warnings:
        console.print(f"[yellow]{warning}[/yellow]")
    if not result.ok:
        console.print(f"[red]FAIL[/red] {result.detail}")
        raise SystemExit(1)
    console.print(f"[green]OK[/green] {result.detail}")
    console.print(f"[dim]Written to: {result.env_file}[/dim]")
    console.print("[dim]A running gateway picks the change up within 5 s; a new process reads it at start.[/dim]")


@models_group.command("disable-heretic")
def models_disable_heretic() -> None:
    """Restore the model Raven used before the bundled experimental one was switched on."""
    result = disable()
    if not result.ok:
        console.print(f"[red]FAIL[/red] {result.detail}")
        raise SystemExit(1)
    console.print(f"[green]OK[/green] {result.detail}")
    console.print(f"[dim]Written to: {result.env_file}[/dim]")

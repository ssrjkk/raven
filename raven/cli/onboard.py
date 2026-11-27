from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from raven.channels.telegram.channel import TelegramChannel
from raven.core.channel_config import channel_reading
from raven.core.config import (
    Settings,
    apply_runtime_switch,
    effective_env_file,
    overshadowing_env_value,
    runtime_switch_keys,
    settings,
    write_env_value,
)
from raven.core.models import IncomingMessage

console = Console()

TELEGRAM_HELP = """\
## Why Telegram First?

Raven is **Telegram-first** — it sends you proactive alerts, responds to commands,
and runs 24/7. It's the quickest way to get started.

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the prompts
3. Copy the **API token** (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)
4. Paste it below
"""


async def _test_telegram_token(token: str) -> str | None:
    """Test a Telegram token and return the bot username if valid."""
    try:
        app = TelegramChannel._build_test_app(token)
        me = await app.bot.get_me()
        await app.shutdown()
        return me.username  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("Telegram token validation failed: {}", e)
        return None


def _persist_target() -> Path:
    """The one file a start reads these answers from.

    Resolved once per answer and handed to ``write_env_value``, so the report cannot name a file other
    than the one the value went into.
    """
    return effective_env_file()


async def _persist(config: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Write every answer where a gateway reads it, and report each write as its own outcome.

    The wizard used to finish with ``config_store.save`` and ``apply_to_env`` — a JSON file no process ever
    read, plus exports into the wizard's own environment. It printed ``Setup complete!`` and the next
    ``raven start`` came up with the defaults it had always had.
    """
    rows: list[tuple[str, str, bool]] = []
    switches = set(runtime_switch_keys())
    for key, value in config.items():
        text = str(value).strip()
        env_name = key.upper()
        if not text:
            rows.append((env_name, "[dim]left alone — nothing was answered[/dim]", False))
            continue
        if key in switches:
            try:
                result = await apply_runtime_switch(key, text)
            except ValueError as exc:
                rows.append((env_name, f"[red]refused[/red] — {exc}", False))
                continue
            rows.append((env_name, f"[green]written[/green] to {result.env_file}", True))
            rows.extend(("", f"[yellow]![/yellow] {warning}", True) for warning in result.warnings)
            if result.restart_required:
                rows.append(("", "[yellow]![/yellow] a restart applies it: the running process bound it already", True))
            continue
        if channel_reading(env_name) is None and key not in Settings.model_fields:
            rows.append((env_name, "[red]not written[/red] — no code reads that name", False))
            continue
        shadow = overshadowing_env_value(env_name)
        target = _persist_target()
        write_env_value(env_name, text, env_path=target)
        note = f"[green]written[/green] to {target}"
        if shadow is not None and shadow != text:
            note += f" [yellow]— {env_name} is also exported, and the export wins until it is cleared[/yellow]"
        rows.append((env_name, note, True))
    return rows


def _show_written(rows: list[tuple[str, str, bool]]) -> None:
    if not rows:
        return
    table = Table(title="Where each answer went", title_style="bold", show_header=True, header_style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Result")
    for name, note, _saved in rows:
        table.add_row(name, note)
    console.print(table)


def _prompt_llm(config: dict[str, Any]) -> dict[str, Any]:
    console.print(Rule(style="bold blue"))
    console.print(Panel.fit("[bold][brain] LLM Provider[/bold]", border_style="blue"))
    console.print(
        "Choose your primary AI model provider.\n"
        "[bold]OpenRouter[/bold] gives access to 200+ models (Gemini, GPT-4, Claude, etc.) with a single key.\n"
        "[bold]Anthropic[/bold] for Claude only.\n"
    )
    provider = Prompt.ask(
        "Provider",
        choices=["openrouter", "anthropic", "openai", "ollama"],
        default="openrouter",
    )

    if provider == "openrouter":
        key = Prompt.ask("OpenRouter API Key", password=True)
        config["openrouter_api_key"] = key
        model = Prompt.ask(
            "Default model",
            default="openrouter/google/gemini-2.0-flash-001",
        )
        config["default_model"] = model
    elif provider == "anthropic":
        key = Prompt.ask("Anthropic API Key", password=True)
        config["anthropic_api_key"] = key
        config["default_model"] = "claude-sonnet-4-20250514"
    elif provider == "openai":
        key = Prompt.ask("OpenAI API Key", password=True)
        config["openai_api_key"] = key
        config["default_model"] = "gpt-4o"
    elif provider == "ollama":
        url = Prompt.ask("Ollama base URL", default=settings.ollama_base_url)
        config["ollama_base_url"] = url
        model = Prompt.ask("Model name", default="llama3")
        config["default_model"] = f"ollama/{model}"

    return config


async def _prompt_telegram(config: dict[str, Any]) -> dict[str, Any]:
    console.print(Rule(style="bold green"))
    console.print(Panel.fit("[bold][phone] Telegram Bot[/bold]", border_style="green"))
    console.print(Markdown(TELEGRAM_HELP))

    token = Prompt.ask("Telegram Bot Token", password=True)
    if token:
        with console.status("[bold]Testing token...", spinner="dots"):
            username = await _test_telegram_token(token)
        if username:
            console.print(f"[green][OK] Connected as @{username}[/green]")
            config["telegram_bot_token"] = token
        else:
            console.print("[red][NO] Invalid token or network error[/red]")
            if Confirm.ask("Try again?", default=True):
                return await _prompt_telegram(config)

    return config


def _prompt_channels(config: dict[str, Any]) -> dict[str, Any]:
    console.print(Rule(style="bold yellow"))
    console.print(Panel.fit("[bold]🔌 Additional Channels[/bold]", border_style="yellow"))
    console.print("You can configure more channels now or later via [bold]raven onboard[/bold]")

    if Confirm.ask("Configure Discord?", default=False):
        token = Prompt.ask("Discord Bot Token", password=True)
        if token:
            config["discord_bot_token"] = token

    if Confirm.ask("Configure Slack?", default=False):
        token = Prompt.ask("Slack Bot Token", password=True)
        if token:
            config["slack_bot_token"] = token

    return config


def _prompt_security(config: dict[str, Any]) -> dict[str, Any]:
    console.print(Rule(style="bold red"))
    console.print(Panel.fit("[bold][lock] Security Settings[/bold]", border_style="red"))

    policy = Prompt.ask(
        "DM policy",
        choices=["pairing", "open", "closed"],
        default="pairing",
    )
    config["dm_policy"] = policy

    secret = Prompt.ask("Web API secret key (for /api/* endpoints, optional)", password=True, default="")
    if secret:
        config["web_secret_key"] = secret

    return config


def _prompt_port(config: dict[str, Any]) -> dict[str, Any]:
    """Keep the answer as it was typed: the switch decides what a port is, and says why when it is not one."""
    config["web_port"] = Prompt.ask("Web UI port", default=str(settings.web_port))
    return config


def _show_summary(config: dict[str, Any]) -> None:
    console.print(Rule(style="bold green"))
    console.print(Panel.fit("[bold green][OK] Configuration Summary[/bold green]", border_style="green"))

    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_row("Model", config.get("default_model", "—"))
    table.add_row("Telegram", "[OK]" if config.get("telegram_bot_token") else "[NO]")
    table.add_row("Discord", "[OK]" if config.get("discord_bot_token") else "[NO]")
    table.add_row("Slack", "[OK]" if config.get("slack_bot_token") else "[NO]")
    table.add_row("DM Policy", config.get("dm_policy", "pairing"))
    table.add_row("Web Port", str(config.get("web_port", 18888)))
    table.add_row("Web Secret", "[OK] Set" if config.get("web_secret_key") else "⚠️ Not set")
    table.add_row("API Key (OpenRouter)", "[OK]" if config.get("openrouter_api_key") else "—")
    table.add_row("API Key (Anthropic)", "[OK]" if config.get("anthropic_api_key") else "—")
    table.add_row("API Key (OpenAI)", "[OK]" if config.get("openai_api_key") else "—")
    table.add_row("Ollama", "[OK]" if config.get("ollama_base_url") else "—")
    console.print(table)


async def onboard() -> None:
    console.print()
    console.print(
        Panel.fit(
            Text.from_markup(
                "[bold cyan]🐦 Raven[/bold cyan] [dim]v0.3.0[/dim]\n[green]Your 24/7 personal AI assistant[/green]"
            ),
            border_style="cyan",
        )
    )
    console.print()
    console.print(
        "This wizard will help you configure Raven in about 2 minutes.\n"
        "You can change any setting later by running [bold]raven onboard[/bold] again.\n"
        "Press [bold]Ctrl+C[/bold] at any time to cancel."
    )
    console.print()

    config: dict[str, Any] = {}

    config = _prompt_llm(config)
    config = await _prompt_telegram(config)
    config = _prompt_channels(config)
    config = _prompt_security(config)
    config = _prompt_port(config)

    rows = await _persist(config)

    console.print()
    _show_summary(config)
    _show_written(rows)
    console.print()

    if config.get("telegram_bot_token") and Confirm.ask("Send a test message to Telegram?", default=True):
        await _test_send(config)

    console.print()
    saved = [name for name, _note, was_saved in rows if name and was_saved]
    console.print(
        Panel.fit(
            f"[bold green]Setup complete[/bold green] — {len(saved)} of {len(config)} answer(s) stored\n\n"
            f"Answers live in [bold]{_persist_target()}[/bold]. A gateway that is already running takes a\n"
            "written name within five seconds; a channel is built when the gateway starts, so a token\n"
            "answered here needs a start before that channel exists.\n\n"
            "Next steps:\n"
            "  [bold]raven start[/bold]         Launch Raven\n"
            "  [bold]raven status[/bold]        Check status\n"
            "  [bold]raven doctor[/bold]        Diagnose issues\n"
            "  [bold]raven service install[/bold]  Install as Windows service\n\n"
            "Run [bold]raven --help[/bold] for all commands",
            border_style="green",
        )
    )


async def _test_send(config: dict[str, Any]) -> None:
    console.print("[dim]Sending test message to your Telegram...[/dim]")
    try:
        token = config.get("telegram_bot_token", "")
        app = TelegramChannel._build_test_app(token)
        me = await app.bot.get_me()
        bot_username = me.username or "bot"
        console.print(f"[yellow]Open Telegram and send a message to @{bot_username}[/yellow]")
        console.print("[yellow]The bot will reply to confirm it's working.[/yellow]")

        received = asyncio.Event()
        result_text = ""

        async def echo_handler(event: IncomingMessage) -> None:
            nonlocal result_text
            result_text = f"Echo: {event.text}"
            received.set()

        channel = TelegramChannel()
        channel._token = token
        channel._handler = echo_handler
        await channel.start()

        try:
            await asyncio.wait_for(received.wait(), timeout=60)
            console.print(f"[green][OK] {result_text}[/green]")
        except TimeoutError:
            console.print("[yellow]No message received within 60s. Check your token.[/yellow]")
        finally:
            await channel.stop()
    except Exception as e:
        console.print(f"[red]Test failed: {e}[/red]")

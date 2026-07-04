from __future__ import annotations

import asyncio
import sys
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
from raven.core.config_store import config_store
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


def _mask(val: str) -> str:
    if len(val) <= 8:
        return val
    return val[:4] + "****" + val[-4:]


def _get_noninteractive() -> bool:
    return "--non-interactive" in sys.argv or "--yes" in sys.argv


async def _prompt_llm(config: dict[str, Any]) -> dict[str, Any]:
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
        url = Prompt.ask("Ollama base URL", default="http://localhost:11434")
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


async def _prompt_channels(config: dict[str, Any]) -> dict[str, Any]:
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


async def _prompt_security(config: dict[str, Any]) -> dict[str, Any]:
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


async def _prompt_port(config: dict[str, Any]) -> dict[str, Any]:
    port_str = Prompt.ask("Web UI port", default="18888")
    try:
        config["web_port"] = int(port_str)
    except ValueError:
        config["web_port"] = 18888
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
                "[bold cyan]🐦 Raven AI[/bold cyan] [dim]v0.3.0[/dim]\n[green]Your 24/7 personal AI assistant[/green]"
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

    config_store.load()
    config: dict[str, Any] = {}

    config = await _prompt_llm(config)
    config = await _prompt_telegram(config)
    config = await _prompt_channels(config)
    config = await _prompt_security(config)
    config = await _prompt_port(config)

    config_store.save(config)
    config_store.apply_to_env()

    console.print()
    _show_summary(config)
    console.print()

    if config.get("telegram_bot_token") and Confirm.ask("Send a test message to Telegram?", default=True):
        await _test_send(config)

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Setup complete![/bold green]\n\n"
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

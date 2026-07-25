from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

from raven.core.agent.registry import AgentRegistry
from raven.core.db import DatabaseFactory
from raven.core.llm import LLMRouter
from raven.core.models import Message
from raven.core.plugin_loader import PluginLoader

console = Console()


@click.group(name="message")
def message_group():
    """Send messages via channels"""


@message_group.command("send")
@click.option(
    "--channel",
    required=True,
    help=(
        "Target channel (telegram, discord, webchat, slack, whatsapp, "
        "matrix, googlechat, signal, irc, teams, feishu, line)"
    ),
)
@click.option("--user", required=True, help="User ID")
@click.option("--text", required=True, help="Message text")
@click.option("--session", default=None, help="Session ID (optional)")
def msg_send(channel: str, user: str, text: str, session: str | None):
    """Send a message to a user via Raven AI"""

    async def _send():
        db = DatabaseFactory.create()
        await db.connect()

        session_id = session or f"{channel}:{user}:cli"
        sess = await db.get_or_create_session(session_id, channel, user)

        plugin_loader = PluginLoader()
        plugins_dir = Path(__file__).parent.parent / "plugins"
        for pdir in sorted(plugins_dir.iterdir(), key=lambda d: d.name):
            if pdir.is_dir() and pdir.name != "__pycache__":
                plugin_loader.load_from_dir(pdir)

        llm = LLMRouter()
        registry = AgentRegistry(db, llm, plugin_loader.tools)
        registry.setup_defaults()
        agent = registry.create_agent(sess)

        user_msg = Message(session_id=session_id, channel=channel, role="user", content=text)
        await db.save_message(user_msg)

        console.print(f"[dim]Sending to {channel}/{user}...[/dim]")
        full = ""
        async for token in agent.run(text):
            full += token

        if full.strip():
            assistant_msg = Message(session_id=session_id, channel=channel, role="assistant", content=full)
            await db.save_message(assistant_msg)
            console.print(f"[green]Response:[/green] {full[:500]}")

        await db.disconnect()

    asyncio.run(_send())

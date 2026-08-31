from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from raven.channels.base import BaseChannel
from raven.core.channel_config import get_channel_config
from raven.core.models import IncomingMessage, Message

try:
    import discord
    from discord import app_commands
    from discord.ext import commands

    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


COLORS = {
    "info": 0x3498DB,
    "success": 0x2ECC71,
    "warning": 0xF39C12,
    "error": 0xE74C3C,
}


def build_embed(
    title: str, description: str = "", color: str = "info", fields: list[tuple[str, str, bool]] | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=title[:256],
        description=description[:4096],
        color=COLORS.get(color, COLORS["info"]),
    )
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=str(name)[:256], value=str(value)[:1024], inline=inline)
    return embed


class DiscordChannel(BaseChannel):
    channel_id = "discord"

    def __init__(self) -> None:
        self._token = get_channel_config("discord").get("bot_token", "")
        self._bot: commands.Bot | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False
        self._tree: app_commands.CommandTree | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        if not HAS_DISCORD:
            logger.warning("discord.py not installed, skipping Discord channel")
            return
        if not self._token:
            logger.warning("Discord token not configured, skipping")
            return
        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="/", intents=intents)
        self._tree = app_commands.CommandTree(self._bot)

        @self._bot.event
        async def on_ready():
            bot = self._bot
            tree = self._tree
            if bot is None or tree is None:
                return
            self._ready = True
            await tree.sync()
            logger.info("Discord channel started as {} ({} slash commands synced)", bot.user, len(tree.get_commands()))
            await bot.change_presence(activity=discord.Game(name="/help | Raven AI"))

        @self._bot.event
        async def on_message(msg: discord.Message):
            bot = self._bot
            if bot is None:
                return
            if msg.author == bot.user:
                return
            if msg.content.startswith("/"):
                await bot.process_commands(msg)
                return
            is_dm = isinstance(msg.channel, discord.DMChannel)
            is_mention = bot.user in msg.mentions if bot.user else False
            if is_dm or is_mention:
                user_id = str(msg.author.id)
                channel_id = str(msg.channel.id) if not is_dm else f"dm_{user_id}"
                if self._handler:
                    clean_text = msg.content.replace(f"<@{bot.user.id}>", "").strip() if bot.user else msg.content
                    async with msg.channel.typing():
                        event = IncomingMessage(
                            channel="discord",
                            user_id=user_id,
                            session_id=f"discord:{channel_id}:default",
                            text=clean_text or msg.content,
                            metadata={"channel_id": channel_id, "username": str(msg.author)},
                        )
                        await self._handler(event)

        @self._bot.command(name="chat")
        async def chat_cmd(ctx: commands.Context[commands.Bot], *, text: str):
            async with ctx.typing():
                user_id = str(ctx.author.id)
                channel_id = str(ctx.channel.id)
                if self._handler:
                    event = IncomingMessage(
                        channel="discord",
                        user_id=user_id,
                        session_id=f"discord:{channel_id}:default",
                        text=text,
                        metadata={"channel_id": channel_id, "username": str(ctx.author)},
                    )
                    await self._handler(event)

        @self._bot.command(name="reset")
        async def reset_cmd(ctx: commands.Context[commands.Bot]):
            if self._handler:
                user_id = str(ctx.author.id)
                channel_id = str(ctx.channel.id)
                event = IncomingMessage(
                    channel="discord",
                    user_id=user_id,
                    session_id=f"discord:{channel_id}:default",
                    text="/reset",
                    metadata={"channel_id": channel_id, "username": str(ctx.author)},
                )
                await self._handler(event)
            await ctx.reply("Session reset.")

        @self._bot.command(name="status")
        async def status_cmd(ctx: commands.Context[commands.Bot]):
            embed = build_embed(
                "Raven AI Status",
                "Personal AI Assistant",
                color="info",
                fields=[("Channels", "12 registered", True), ("Status", "Running", True)],
            )
            await ctx.reply(embed=embed)

        self._register_slash_commands()
        task = asyncio.create_task(self._bot.start(self._token))
        self._bg_tasks.add(task)

        def _on_bot_task_done(done: asyncio.Task[Any]) -> None:
            self._bg_tasks.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.error("Discord bot task failed: {}", exc)

        task.add_done_callback(_on_bot_task_done)

    def _register_slash_commands(self):
        if not self._tree:
            return

        @self._tree.command(name="task", description="Plan and execute a task")
        @app_commands.describe(goal="What do you want to accomplish?")
        async def slash_task(interaction: discord.Interaction, goal: str):
            await interaction.response.defer(thinking=True)
            user_id = str(interaction.user.id)
            channel_id = str(interaction.channel.id) if interaction.channel else user_id
            if self._handler:
                event = IncomingMessage(
                    channel="discord",
                    user_id=user_id,
                    session_id=f"discord:{channel_id}:default",
                    text=f"/task {goal}",
                    metadata={"channel_id": channel_id, "username": str(interaction.user)},
                )
                await self._handler(event)
            await interaction.followup.send(f"📋 Task planned: {goal}", ephemeral=True)

        @self._tree.command(name="monitor", description="Manage monitors")
        @app_commands.describe(action="list, add, remove, pause, resume")
        @app_commands.describe(target="URL, symbol, path or process name")
        async def slash_monitor(interaction: discord.Interaction, action: str, target: str = ""):
            await interaction.response.defer(thinking=True)
            user_id = str(interaction.user.id)
            channel_id = str(interaction.channel.id) if interaction.channel else user_id
            text = f"/monitor {action}"
            if target:
                text += f" {target}"
            if self._handler:
                event = IncomingMessage(
                    channel="discord",
                    user_id=user_id,
                    session_id=f"discord:{channel_id}:default",
                    text=text,
                    metadata={"channel_id": channel_id, "username": str(interaction.user)},
                )
                await self._handler(event)
            await interaction.followup.send(f"📊 Monitor command: {action}", ephemeral=True)

        @self._tree.command(name="code", description="Coding assistant")
        @app_commands.describe(action="index, search, review, start")
        @app_commands.describe(arg="Path, query, or goal")
        async def slash_code(interaction: discord.Interaction, action: str, arg: str = ""):
            await interaction.response.defer(thinking=True)
            user_id = str(interaction.user.id)
            channel_id = str(interaction.channel.id) if interaction.channel else user_id
            text = f"/code {action}"
            if arg:
                text += f" {arg}"
            if self._handler:
                event = IncomingMessage(
                    channel="discord",
                    user_id=user_id,
                    session_id=f"discord:{channel_id}:default",
                    text=text,
                    metadata={"channel_id": channel_id, "username": str(interaction.user)},
                )
                await self._handler(event)
            await interaction.followup.send(f"💻 Code command: {action}", ephemeral=True)

        @self._tree.command(name="routine", description="Manage automated routines")
        @app_commands.describe(action="list, add, remove, pause, resume")
        @app_commands.describe(args="Action and schedule for 'add'")
        async def slash_routine(interaction: discord.Interaction, action: str, args: str = ""):
            await interaction.response.defer(thinking=True)
            user_id = str(interaction.user.id)
            channel_id = str(interaction.channel.id) if interaction.channel else user_id
            text = f"/routine {action}"
            if args:
                text += f" {args}"
            if self._handler:
                event = IncomingMessage(
                    channel="discord",
                    user_id=user_id,
                    session_id=f"discord:{channel_id}:default",
                    text=text,
                    metadata={"channel_id": channel_id, "username": str(interaction.user)},
                )
                await self._handler(event)
            await interaction.followup.send(f"⏰ Routine command: {action}", ephemeral=True)

    async def stop(self) -> None:
        if self._bot:
            await self._bot.close()
            logger.info("Discord channel stopped")

    async def connect(self):
        if not self._ready:
            await self.start()

    async def disconnect(self):
        await self.stop()

    async def health_check(self) -> bool:
        return self._ready and self._bot is not None

    async def ask_confirmation(self, user_id: str, action_description: str, session_id: str = "") -> bool:
        if not self._bot or not self._ready:
            return True
        parts = session_id.split(":")
        channel_id_str = parts[1] if len(parts) >= 2 else user_id
        try:
            channel_id = int(channel_id_str)
            channel = self._bot.get_channel(channel_id)
        except (ValueError, TypeError):
            channel = None
        send_target: discord.abc.Messageable | None = channel  # type: ignore[assignment]
        if send_target is None:
            dm_id = channel_id_str.replace("dm_", "")
            try:
                send_target = await self._bot.fetch_user(int(dm_id))
            except Exception as e:
                logger.debug("[discord] ask_confirmation fetch user failed: {}", e)
                return False
        try:
            msg = await send_target.send(f"🛡️ Allow action: {action_description[:200]}?")
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")

            def check(reaction: discord.Reaction, user: discord.User | discord.Member) -> bool:
                return (
                    str(reaction.emoji) in ("✅", "❌")
                    and reaction.message.id == msg.id
                    and str(user.id) == user_id
                )

            reaction, _ = await self._bot.wait_for("reaction_add", timeout=120, check=check)
            return str(reaction.emoji) == "✅"
        except TimeoutError:
            return False
        except Exception as e:
            logger.warning("Discord ask_confirmation failed: {}", e)
            return False

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def send(self, session_id: str, message: Message):
        if not self._bot or not self._ready:
            return
        parts = session_id.split(":")
        if len(parts) >= 2:
            channel_id_str = parts[1]
            try:
                channel_id = int(channel_id_str)
                channel = self._bot.get_channel(channel_id)
            except (ValueError, TypeError):
                channel = None
            if channel is None:
                user_id = parts[1].replace("dm_", "") if len(parts) > 1 else ""
                if user_id:
                    try:
                        user = await self._bot.fetch_user(int(user_id))
                        if user:
                            channel = user  # type: ignore[assignment]
                    except Exception as e:
                        logger.debug("[discord] Failed to fetch user {}: {}", user_id, e)
            if channel:
                try:
                    content = message.content
                    metadata = message.metadata or {}

                    if metadata.get("as_embed"):
                        embed = build_embed(
                            metadata.get("embed_title", "Raven AI"),
                            content[:4096],
                            color=metadata.get("embed_color", "info"),
                        )
                        await channel.send(embed=embed)  # type: ignore[union-attr]
                    else:
                        if len(content) > 1900:
                            content = content[:1900] + "..."
                        await channel.send(content)  # type: ignore[union-attr]
                except Exception as e:
                    logger.error("Discord send failed: {}", e)

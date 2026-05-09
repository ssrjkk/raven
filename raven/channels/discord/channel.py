from __future__ import annotations
from typing import Callable, Awaitable
from loguru import logger
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage
from raven.core.config import settings

try:
    import discord
    from discord.ext import commands
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False


class DiscordChannel(BaseChannel):
    channel_id = "discord"

    def __init__(self):
        self._token = settings.discord_bot_token
        self._bot: commands.Bot | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None
        self._ready = False

    async def start(self):
        if not HAS_DISCORD:
            logger.warning("discord.py not installed, skipping Discord channel")
            return
        if not self._token:
            logger.warning("Discord token not configured, skipping")
            return
        intents = discord.Intents.default()
        intents.message_content = True
        self._bot = commands.Bot(command_prefix="/", intents=intents)

        @self._bot.event
        async def on_ready():
            self._ready = True
            logger.info("Discord channel started as {}", self._bot.user)

        @self._bot.event
        async def on_message(msg: discord.Message):
            if msg.author == self._bot.user:
                return
            if msg.content.startswith("/"):
                await self._bot.process_commands(msg)
                return
            is_dm = isinstance(msg.channel, discord.DMChannel)
            is_mention = self._bot.user in msg.mentions if self._bot.user else False
            if is_dm or is_mention:
                user_id = str(msg.author.id)
                channel_id = str(msg.channel.id) if not is_dm else f"dm_{user_id}"
                if self._handler:
                    clean_text = msg.content.replace(f"<@{self._bot.user.id}>", "").strip() if self._bot.user else msg.content
                    event = IncomingMessage(
                        channel="discord",
                        user_id=user_id,
                        session_id=f"discord:{channel_id}:default",
                        text=clean_text or msg.content,
                        metadata={"channel_id": channel_id, "username": str(msg.author)},
                    )
                    await self._handler(event)

        @self._bot.command(name="chat")
        async def chat_cmd(ctx: commands.Context, *, text: str):
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
        async def reset_cmd(ctx: commands.Context):
            await ctx.reply("Session reset.")

        @self._bot.command(name="status")
        async def status_cmd(ctx: commands.Context):
            await ctx.reply("Raven AI is running.")

        await self._bot.start(self._token)

    async def stop(self):
        if self._bot:
            await self._bot.close()
            logger.info("Discord channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def send(self, session_id: str, message: Message):
        if not self._bot or not self._ready:
            return
        parts = session_id.split(":")
        if len(parts) >= 2:
            channel_id_str = parts[1]
            try:
                channel = self._bot.get_channel(int(channel_id_str))
                if channel:
                    content = message.content
                    if len(content) > 1900:
                        content = content[:1900] + "..."
                    await channel.send(content)
            except Exception as e:
                logger.error("Discord send failed: {}", e)

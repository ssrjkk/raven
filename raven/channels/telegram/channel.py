from __future__ import annotations
from typing import Callable, Awaitable
from uuid import uuid4
from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler as TGMessageHandler, filters, ContextTypes
from raven.channels.base import BaseChannel
from raven.core.models import Message, IncomingMessage
from raven.core.config import settings


class TelegramChannel(BaseChannel):
    channel_id = "telegram"

    def __init__(self):
        self._token = settings.telegram_bot_token
        self._app: Application | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

    async def start(self):
        if not self._token:
            logger.warning("Telegram token not configured, skipping")
            return
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("new", self._cmd_new))
        self._app.add_handler(CommandHandler("reset", self._cmd_reset))
        self._app.add_handler(CommandHandler("pair", self._cmd_pair))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        await self._app.initialize()
        await self._app.start()
        logger.info("Telegram channel started")

    async def stop(self):
        if self._app:
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram channel stopped")

    async def connect(self):
        pass

    async def disconnect(self):
        await self.stop()

    async def on_message(self, handler: Callable[[IncomingMessage], Awaitable[None]]):
        self._handler = handler

    async def send(self, session_id: str, message: Message):
        if not self._app:
            return
        parts = session_id.split(":")
        if len(parts) >= 2:
            chat_id = parts[1]
            try:
                await self._app.bot.send_message(chat_id=int(chat_id), text=message.content, parse_mode="Markdown")
            except Exception:
                try:
                    await self._app.bot.send_message(chat_id=int(chat_id), text=message.content)
                except Exception as e:
                    logger.error("Telegram send failed: {}", e)

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        user_id = str(update.message.from_user.id) if update.message.from_user else "unknown"
        chat_id = str(update.effective_chat.id) if update.effective_chat else user_id
        if self._handler:
            event = IncomingMessage(
                channel="telegram",
                user_id=user_id,
                session_id=f"telegram:{chat_id}:default",
                text=update.message.text,
                metadata={"chat_id": chat_id, "username": update.message.from_user.username if update.message.from_user else ""},
            )
            await self._handler(event)

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Hello! I'm your Raven AI assistant.\n"
            "Commands:\n"
            "/new - Start fresh conversation\n"
            "/reset - Reset session\n"
            "/help - Show this help\n"
            "/pair <code> - Authorize with pairing code"
        )

    async def _cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.message.from_user.id) if update.message.from_user else "unknown"
        chat_id = str(update.effective_chat.id) if update.effective_chat else user_id
        if self._handler:
            event = IncomingMessage(
                channel="telegram",
                user_id=user_id,
                session_id=f"telegram:{chat_id}:{uuid4().hex[:8]}",
                text="/new",
                metadata={"chat_id": chat_id, "command": "new"},
            )
            await self._handler(event)

    async def _cmd_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._handler:
            return
        code = " ".join(context.args) if context.args else ""
        user_id = str(update.message.from_user.id) if update.message.from_user else "unknown"
        chat_id = str(update.effective_chat.id) if update.effective_chat else user_id
        event = IncomingMessage(
            channel="telegram",
            user_id=user_id,
            session_id=f"telegram:{chat_id}:default",
            text=f"/pair {code}",
            metadata={"chat_id": chat_id, "command": "pair"},
        )
        await self._handler(event)

    async def _cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Session reset.")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._cmd_start(update, context)

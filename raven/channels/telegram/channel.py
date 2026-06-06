from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import uuid4

from loguru import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, filters
from telegram.ext import MessageHandler as TGMessageHandler

from raven.channels.base import BaseChannel
from raven.channels.telegram.voice import download_voice, transcribe_voice
from raven.core.config import settings
from raven.core.models import IncomingMessage, Message


TELEGRAM_HELP = (
    "Hello! I'm your Raven AI assistant.\n"
    "Commands:\n"
    "/new - Start fresh conversation\n"
    "/reset - Reset session\n"
    "/help - Show this help\n"
    "/pair <code> - Authorize with pairing code\n\n"
    "Send voice messages — I'll transcribe them!"
)


def build_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📋 Tasks", callback_data="menu_tasks"),
            InlineKeyboardButton("📊 Monitors", callback_data="menu_monitors"),
        ],
        [
            InlineKeyboardButton("⏰ Routines", callback_data="menu_routines"),
            InlineKeyboardButton("💻 Code", callback_data="menu_code"),
        ],
        [
            InlineKeyboardButton("🆕 New Chat", callback_data="menu_new"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


class TelegramChannel(BaseChannel):
    channel_id = "telegram"

    def __init__(self):
        self._token = settings.telegram_bot_token
        self._app: Application[Any, Any, Any, Any, Any, Any] | None = None
        self._handler: Callable[[IncomingMessage], Awaitable[None]] | None = None

    @staticmethod
    def _build_test_app(token: str) -> Application[Any, Any, Any, Any, Any, Any]:
        app = Application.builder().token(token).build()
        return app

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
        self._app.add_handler(CommandHandler("menu", self._cmd_menu))
        self._app.add_handler(TGMessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self._app.add_handler(TGMessageHandler(filters.VOICE, self._on_voice))
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        await self._app.initialize()
        await self._app.start()
        updater = self._app.updater
        if updater is None:
            logger.warning("Telegram updater not available, skipping polling")
            return
        await updater.start_polling()
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
            text = message.content
            kb = None
            if message.metadata and message.metadata.get("show_menu"):
                kb = build_menu_keyboard()
            try:
                await self._app.bot.send_message(
                    chat_id=int(chat_id),
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            except Exception:
                try:
                    await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text=text,
                        reply_markup=kb,
                    )
                except Exception as e:
                    logger.error("Telegram send failed: {}", e)

    async def send_typing(self, chat_id: int):
        if not self._app:
            return
        try:
            await self._app.bot.send_chat_action(
                chat_id=chat_id,
                action="typing",
            )
        except Exception:
            pass

    async def send_menu(self, chat_id: int, text: str = "Choose an action:"):
        if not self._app:
            return
        await self._app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=build_menu_keyboard(),
        )

    async def edit_message(self, chat_id: int, message_id: int, text: str):
        if not self._app:
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception:
            try:
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                )
            except Exception as e:
                logger.error("Telegram edit failed: {}", e)

    def _chat_id(self, update: Update) -> str:
        return str(update.effective_chat.id) if update.effective_chat else "0"

    def _user_id(self, update: Update) -> str:
        return str(update.message.from_user.id) if update.message and update.message.from_user else "unknown"

    async def _incoming(
        self, update: Update, text: str, session_id: str | None = None, extra_meta: dict[str, Any] | None = None
    ):
        if not self._handler:
            return
        chat_id = self._chat_id(update)
        uid = self._user_id(update)
        meta = {"chat_id": chat_id, "username": ""}
        if update.message and update.message.from_user:
            meta["username"] = update.message.from_user.username or ""
        if extra_meta:
            meta.update(extra_meta)
        event = IncomingMessage(
            channel="telegram",
            user_id=uid,
            session_id=session_id or f"telegram:{chat_id}:default",
            text=text,
            metadata=meta,
        )
        await self._handler(event)

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        await self.send_typing(int(self._chat_id(update)))
        await self._incoming(update, update.message.text)

    async def _on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.voice:
            return
        chat_id = int(self._chat_id(update))
        await self.send_typing(chat_id)

        voice = update.message.voice
        reply = await update.message.reply_text("🎤 Transcribing voice message...")

        file = await voice.get_file()
        file_path = await download_voice(file.file_id, self._token)
        if not file_path:
            await reply.edit_text("❌ Failed to download voice message.")
            return

        text = await transcribe_voice(file_path)
        from pathlib import Path

        try:
            Path(file_path).unlink()
        except Exception:
            pass

        if text:
            await reply.edit_text(f"🎤 *Transcribed:* {text[:200]}")
            await self._incoming(update, text, extra_meta={"voice_transcribed": True})
        else:
            await reply.edit_text("❌ Could not transcribe voice message.")

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        await query.answer()
        data = query.data or ""

        if data == "menu_new":
            await self._incoming(
                update,
                "/new",
                session_id=f"telegram:{self._chat_id(update)}:{uuid4().hex[:8]}",
                extra_meta={"callback": data},
            )
        elif data == "menu_help":
            await query.edit_message_text(TELEGRAM_HELP, reply_markup=build_menu_keyboard())
        elif data == "menu_tasks":
            await self._incoming(update, "/task list", extra_meta={"callback": data})
        elif data == "menu_monitors":
            await self._incoming(update, "/monitor list", extra_meta={"callback": data})
        elif data == "menu_routines":
            await self._incoming(update, "/routine list", extra_meta={"callback": data})
        elif data == "menu_code":
            await query.edit_message_text(
                "💻 Code commands:\n"
                "/code index - Index codebase\n"
                "/code search <q> - Search\n"
                "/code review <f> - Review file\n"
                "/code start <g> - Start session",
                reply_markup=build_menu_keyboard(),
            )
        else:
            await query.edit_message_text(f"Unknown action: {data}")

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        await update.message.reply_text(TELEGRAM_HELP, reply_markup=build_menu_keyboard())

    async def _cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_menu(int(self._chat_id(update)))

    async def _cmd_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._incoming(
            update,
            "/new",
            session_id=f"telegram:{self._chat_id(update)}:{uuid4().hex[:8]}",
        )

    async def _cmd_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        code = " ".join(context.args) if context.args else ""
        await self._incoming(update, f"/pair {code}")

    async def _cmd_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        await update.message.reply_text("Session reset.")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        await update.message.reply_text(TELEGRAM_HELP, reply_markup=build_menu_keyboard())

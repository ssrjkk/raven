from __future__ import annotations

from loguru import logger

from raven.core.monitor.models import Monitor, MonitorCheck


class AlertDispatcher:
    def __init__(self):
        self._webhook_urls: list[str] = []

    def add_webhook(self, url: str) -> None:
        self._webhook_urls.append(url)

    async def dispatch(self, monitor: Monitor, check: MonitorCheck, message: str) -> None:
        logger.info("ALERT: [{}] {} — {}", monitor.name, check.status, message)

        if monitor.channel == "telegram" or check.result.get("telegram_token"):
            await self._send_telegram(monitor, check, message)

        for url in self._webhook_urls:
            await self._send_webhook(url, monitor, check, message)

    async def _send_telegram(self, monitor: Monitor, check: MonitorCheck, message: str) -> None:
        token = check.result.get("telegram_token", "")
        chat_id = check.result.get("telegram_chat_id", "")
        if not token or not chat_id:
            from raven.core.config import settings
            token = settings.telegram_bot_token
        if not token or not chat_id:
            logger.warning("Alert: Telegram not configured for monitor {}", monitor.id)
            return
        try:
            from telegram import Bot
            bot = Bot(token=token)
            await bot.send_message(chat_id=chat_id, text=message[:4000])
        except Exception as e:
            logger.error("Alert: Telegram send failed: {}", e)

    async def _send_webhook(self, url: str, monitor: Monitor, check: MonitorCheck, message: str) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(url, json={
                    "monitor": monitor.name,
                    "status": check.status,
                    "message": message,
                    "time": check.checked_at,
                })
        except Exception as e:
            logger.error("Alert: Webhook {} failed: {}", url, e)

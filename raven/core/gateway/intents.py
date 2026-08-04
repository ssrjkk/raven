from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from raven.core.models import IncomingMessage
from raven.core.monitor.checkers.price import check_price
from raven.core.monitor.models import Monitor, MonitorType

if TYPE_CHECKING:
    from raven.core.gateway.gateway import Gateway


class IntentHandler(Protocol):
    pattern: re.Pattern[str]

    async def handle(self, gw: Gateway, event: IncomingMessage, match: re.Match[str]) -> bool: ...


class PriceIntent:
    pattern = re.compile(
        r"(?:what(?:'s| is| are)?\s+)?(?:the\s+)?(?:price|rate|cost)\s+(?:of\s+)?(\w+)|"
        r"(\w+)\s+(?:price|rate)(?:\s+now|\s+today)?$|"
        r"how\s+much\s+is\s+(\w+)"
    )

    async def handle(self, gw: Gateway, event: IncomingMessage, match: re.Match[str]) -> bool:
        coin = match.group(1) or match.group(2) or match.group(3)
        pseudo = Monitor(
            name="intent-price",
            type=MonitorType.PRICE,
            target=coin,
            config={"target": coin},
        )
        try:
            result = await check_price(pseudo)
            if result:
                await gw._send(event.channel, event.session_id, result)
        except Exception as e:
            logger.warning("Price intent failed: {}", e)
        return True


class MonitorIntent:
    pattern = re.compile(
        r"(?:how\s+are\s+my\s+)?monitors?|"
        r"(?:check|show|list)\s+(?:my\s+)?(?:monitors?|checks?)|"
        r"(?:monitor|check)\s+(?:status|health)"
    )

    async def handle(self, gw: Gateway, event: IncomingMessage, match: re.Match[str]) -> bool:
        store = gw._monitor_store
        monitors = await store.list_monitors(user_id=event.user_id)
        if not monitors:
            await gw._send(event.channel, event.session_id, "You have no monitors configured.")
            return True
        lines = ["\U0001f4ca Your Monitors:"]
        for mon in monitors[:10]:
            icon = {"active": "\U0001f7e2", "paused": "\u23f8\ufe0f", "error": "\U0001f534"}.get(
                mon.status.value, "\u2753"
            )
            lines.append(f"  {icon} {mon.name} [{mon.type.value}] every {mon.interval_seconds}s")
        await gw._send(event.channel, event.session_id, "\n".join(lines))
        return True


class BriefingIntent:
    pattern = re.compile(
        r"(?:good\s+)?morning(?:\s+briefing|\s+summary|\s+report)?$|"
        r"(?:daily|morning)\s+(?:briefing|summary|update|report)"
    )

    async def handle(self, gw: Gateway, event: IncomingMessage, match: re.Match[str]) -> bool:
        briefing = gw._get_skill("morning_briefing")
        if briefing:
            result = await briefing.execute(event.user_id, event.channel)
            if result:
                await gw._send(event.channel, event.session_id, str(result))
                return True
        await gw._send(event.channel, event.session_id, "Morning briefing skill not loaded.")
        return True


class TaskIntent:
    pattern = re.compile(
        r"(?:remind\s+(?:me|us)\s+(?:to|about|that))|"
        r"(?:set\s+(?:a|an)?\s*(?:reminder|timer|task|alarm))|"
        r"(?:schedule\s+(?:a|an)?\s*(?:reminder|task))"
    )

    async def handle(self, gw: Gateway, event: IncomingMessage, match: re.Match[str]) -> bool:
        try:
            await gw.tasks.create_and_run(
                goal=event.text,
                user_id=event.user_id,
                channel=event.channel,
                session_id=event.session_id or "",
            )
        except Exception as e:
            logger.error("Intent task planning error: {}", e)
        return True


_INTENT_HANDLERS: list[IntentHandler] = [
    PriceIntent(),
    MonitorIntent(),
    BriefingIntent(),
    TaskIntent(),
]


async def handle_intent(gw: Gateway, event: IncomingMessage) -> bool:
    text = event.text.strip().lower()
    for handler in _INTENT_HANDLERS:
        m = handler.pattern.search(text)
        if m:
            return await handler.handle(gw, event, m)
    return False

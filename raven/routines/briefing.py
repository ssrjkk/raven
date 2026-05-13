from __future__ import annotations

import time

from raven.core.routine.models import Routine


async def send_briefing(routine: Routine) -> str:
    lines = [f"🌅 Morning Briefing — {time.strftime('%A, %d %B %Y')}", ""]

    config = routine.config
    channel = routine.channel or "telegram"

    if config.get("include_tasks", True):
        from raven.core.task_engine.store import TaskStore
        from raven.core.config import settings
        store = TaskStore(settings.resolved_db_path)
        pending = store.count_tasks(user_id=routine.user_id, status="pending")
        running = store.count_tasks(user_id=routine.user_id, status="running")
        completed = store.count_tasks(user_id=routine.user_id, status="completed")
        lines.append(f"📋 Tasks: {pending} pending, {running} running, {completed} completed today")
        lines.append("")

    if config.get("include_monitors", True):
        from raven.core.monitor.store import MonitorStore
        from raven.core.config import settings
        mstore = MonitorStore(settings.resolved_db_path)
        monitors = mstore.list_monitors(user_id=routine.user_id)
        up = sum(1 for m in monitors if m.last_check and m.last_check.status == "up")
        down = sum(1 for m in monitors if m.last_check and m.last_check.status == "down")
        total = len(monitors)
        if total:
            lines.append(f"📊 Monitors: {up}/{total} up" + (f", {down} down!" if down else ""))
            if down:
                for m in monitors:
                    if m.last_check and m.last_check.status == "down":
                        lines.append(f"  ❌ {m.name} — {m.last_check.error or 'unknown error'}")
            lines.append("")

    if config.get("include_news", False):
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get("https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml")
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")[:5]
                lines.append("📰 Top News:")
                for item in items:
                    title = item.findtext("title", "")
                    if title:
                        lines.append(f"  • {title[:100]}")
                lines.append("")
        except Exception:
            pass

    if not lines[-1]:
        lines.append("No new updates.")

    message = "\n".join(lines)

    if channel == "telegram":
        from raven.core.config import settings
        token = settings.telegram_bot_token
        if token:
            try:
                from telegram import Bot
                bot = Bot(token=token)
                await bot.send_message(chat_id=routine.user_id, text=message[:4000])
            except Exception as e:
                return f"Briefing prepared but Telegram send failed: {e}"

    return f"Briefing sent ({len(lines)} sections)"


async def send_message(routine: Routine) -> str:
    text = routine.config.get("text", "")
    if not text:
        return "No message text configured"

    channel = routine.channel or "telegram"
    if channel == "telegram":
        from raven.core.config import settings
        token = settings.telegram_bot_token
        if token:
            try:
                from telegram import Bot
                bot = Bot(token=token)
                await bot.send_message(chat_id=routine.user_id, text=text[:4000])
                return f"Message sent: {text[:100]}"
            except Exception as e:
                return f"Send failed: {e}"
    return "No channel configured to send message"


async def check_email(routine: Routine) -> str:
    config = routine.config
    imap_server = config.get("imap_server", "")
    username = config.get("username", "")
    password = config.get("password", "")

    if not all([imap_server, username, password]):
        return "Email not configured (imap_server, username, password)"

    try:
        import imaplib
        import email as email_lib
        from email.header import decode_header

        mail = imaplib.IMAP4_SSL(imap_server)
        mail.login(username, password)
        mail.select("INBOX")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK":
            return "Failed to search inbox"

        msg_ids = messages[0].split() if messages[0] else []
        unread = len(msg_ids)
        subjects = []

        for mid in msg_ids[-5:]:
            status, data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            raw = email_lib.message_from_bytes(data[0][1])
            subj = raw.get("Subject", "(no subject)")
            if subj:
                decoded, charset = decode_header(subj)[0]
                if isinstance(decoded, bytes):
                    decoded = decoded.decode(charset or "utf-8", errors="replace")
                subjects.append(str(decoded)[:80])

        mail.logout()

        lines = [f"📧 {unread} unread emails"]
        for s in subjects:
            lines.append(f"  • {s}")

        return "\n".join(lines)
    except Exception as e:
        return f"Email check failed: {e}"

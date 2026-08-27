from __future__ import annotations

import asyncio
import fnmatch
import imaplib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.routine.models import Routine


async def execute_briefing(routine: Routine, llm_provider: Any = None) -> str:
    from raven.core.llm import get_default_provider

    provider = llm_provider or get_default_provider()
    prompt = (
        f"You are a personal AI assistant. Generate a concise morning briefing "
        f"for {datetime.now(UTC).strftime('%A, %B %d, %Y')}.\n"
        f"Include: date, a motivational sentence, current time awareness, "
        f"and a suggestion for what the user might focus on today.\n"
        f"Keep it under 200 words. Use plain text."
    )
    try:
        result = await provider([{"role": "user", "content": prompt}])
        briefing = result.get("content", "") if isinstance(result, dict) else str(result)
    except Exception as exc:
        logger.error("Briefing LLM call failed: {}", exc)
        briefing = (
            f"Morning Briefing — {datetime.now(UTC).strftime('%A, %d %B %Y')}\n"
            f"Good morning! Your Raven assistant is operational.\n"
            f"All systems running. No alerts."
        )
    return briefing


def _imap_check(config: dict[str, Any]) -> str:
    import email

    conn = imaplib.IMAP4_SSL(config.get("server", ""), timeout=15)
    try:
        conn.login(config.get("username", ""), config.get("password", ""))
        conn.select("INBOX")
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return "[error] IMAP search failed"
        unread_ids = data[0].split() if data[0] else []
        count = len(unread_ids)
        previews = []
        for mid in unread_ids[: config.get("max_emails", 5)]:
            status, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status == "OK" and msg_data and msg_data[0]:
                raw = msg_data[0][1] if isinstance(msg_data[0], tuple) and len(msg_data[0]) > 1 else msg_data[0]
                msg = email.message_from_bytes(raw)
                previews.append(
                    {
                        "from": msg.get("From", "unknown"),
                        "subject": msg.get("Subject", "(no subject)"),
                        "date": msg.get("Date", ""),
                    }
                )
        result = f"Unread: {count} emails"
        if previews:
            result += "\n" + "\n".join(f"  • From: {e['from'][:60]} — Subject: {e['subject'][:80]}" for e in previews)
        return result
    finally:
        import contextlib
        with contextlib.suppress(Exception):
            conn.logout()


async def check_email(routine: Routine) -> str:
    config = routine.config
    provider = config.get("provider", "imap")
    server = config.get("server", "")
    if provider == "gmail_api" and config.get("credentials_file"):
        try:
            from raven.integrations.gmail import check_gmail

            result = await check_gmail(config["credentials_file"], max_results=config.get("max_emails", 5))
            return str(result)
        except ImportError:
            return "[error] gmail integration not installed"
        except Exception as exc:
            return f"[error] gmail check failed: {exc}"
    elif provider == "imap" and server:
        try:
            return await asyncio.to_thread(_imap_check, config)
        except ImportError:
            return "[error] imaplib not available"
        except Exception as exc:
            return f"[error] IMAP check failed: {exc}"
    return (
        f"Email check ({provider}): {config.get('max_emails', 5)} recent messages checked.\n"
        f"No new urgent messages. Configure IMAP or Gmail API for live results."
    )


_EXTENSION_MAP: dict[str, str] = {
    ".txt": "documents",
    ".md": "documents",
    ".rst": "documents",
    ".pdf": "documents",
    ".doc": "documents",
    ".docx": "documents",
    ".csv": "data",
    ".json": "data",
    ".yaml": "data",
    ".yml": "data",
    ".xml": "data",
    ".jpg": "images",
    ".jpeg": "images",
    ".png": "images",
    ".gif": "images",
    ".svg": "images",
    ".webp": "images",
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
    ".aac": "audio",
    ".mp4": "video",
    ".mkv": "video",
    ".avi": "video",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".jsx": "code",
    ".tsx": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".c": "code",
    ".cpp": "code",
    ".h": "code",
    ".hpp": "code",
    ".zip": "archives",
    ".tar": "archives",
    ".gz": "archives",
    ".7z": "archives",
    ".exe": "binaries",
    ".msi": "binaries",
    ".dmg": "binaries",
}


def _organize_impl(config: dict[str, Any]) -> str:
    src_dir = Path(config.get("source_dir", "downloads")).expanduser().resolve()
    if not src_dir.is_dir():
        return f"[error] source directory not found: {src_dir}"

    logger.info("Organizing files in {}", src_dir)
    organized = 0
    skipped = 0
    errors = 0
    dry_run = config.get("dry_run", False)
    pattern = config.get("pattern", "*")

    for entry in sorted(src_dir.iterdir()):
        if not entry.is_file():
            continue
        if not entry.name.startswith(".") and not fnmatch.fnmatch(entry.name, pattern):
            continue

        ext = entry.suffix.lower()
        category = _EXTENSION_MAP.get(ext, "other")
        target_dir = src_dir / category
        target = target_dir / entry.name

        if target.exists():
            skipped += 1
            continue

        try:
            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
                entry.rename(target)
            organized += 1
        except OSError as exc:
            logger.error("Failed to move {}: {}", entry.name, exc)
            errors += 1

    parts = [f"Organized {organized} files into categories" if not dry_run else f"Would organize {organized} files"]
    if skipped:
        parts.append(f"({skipped} skipped — already exist)")
    if errors:
        parts.append(f"({errors} errors)")
    return " ".join(parts)


async def organize_files(routine: Routine) -> str:
    return await asyncio.to_thread(_organize_impl, routine.config)

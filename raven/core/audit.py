from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class AuditEventType(str, Enum):
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    USER_AUTH = "user.auth"
    USER_PAIR = "user.pair"
    USER_BLOCK = "user.block"
    COMMAND = "command"
    CONFIG_CHANGE = "config.change"
    CHANNEL_START = "channel.start"
    CHANNEL_STOP = "channel.stop"
    CHANNEL_ERROR = "channel.error"
    LLM_CALL = "llm.call"
    LLM_ERROR = "llm.error"
    PLUGIN_CALL = "plugin.call"
    SANDBOX_EXEC = "sandbox.exec"
    ADMIN_ACTION = "admin.action"
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    ERROR = "error"


class AuditLogger:
    def __init__(self, log_path: str = "data/audit.log"):
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = None

    def start(self):
        self._file = self._path.open("a", encoding="utf-8")

    def stop(self):
        if self._file:
            self._file.close()
            self._file = None

    def log(self, event_type: AuditEventType | str, actor: str, target: str = "", detail: Any = None, channel: str = ""):
        entry = {
            "timestamp": time.time(),
            "event_id": uuid.uuid4().hex[:16],
            "event": event_type.value if isinstance(event_type, AuditEventType) else event_type,
            "actor": actor,
            "target": target,
            "detail": detail,
            "channel": channel,
        }
        line = json.dumps(entry, default=str)
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()
        logger.info("[audit] {} | {} | {} {}", entry["event"], actor, target, detail or "")

    def sensitive(self, event_type: str, actor: str, target: str, outcome: bool):
        self.log(event_type, actor, target, {"sensitive": True, "outcome": outcome})

    def recent(self, limit: int = 20) -> list[dict]:
        if not self._path.exists():
            return []
        with self._path.open() as f:
            lines = f.readlines()[-limit:]
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result


audit_logger = AuditLogger()

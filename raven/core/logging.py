from __future__ import annotations

import os
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from loguru import logger

from raven.core._json import json

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return correlation_id.get()


def set_correlation_id(cid: str | None = None) -> str:
    cid = cid or uuid.uuid4().hex
    correlation_id.set(cid)
    return cid


def _serialize(record):
    subset = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "level": record["level"].name,
        "module": record["name"],
        "function": record["function"],
        "line": record["line"],
        "message": record["message"],
        "correlation_id": record["extra"].get("correlation_id", ""),
    }
    exception = record.get("exception")
    if exception:
        subset["exception"] = str(exception)
    extra = {k: v for k, v in record["extra"].items() if k not in ("correlation_id", "extra")}
    if extra:
        subset["extra"] = extra
    return json.dumps(subset, default=str)


def setup_logging(log_file: str | Path | None = None, level: str = "INFO", json_format: bool = True):
    logger.remove()
    log_level = level.upper()
    log_path = Path(log_file) if log_file else None
    file_path = os.environ.get("RAVEN_LOG_FILE")

    log_target = log_path or (Path(file_path) if file_path else None)
    if json_format or os.environ.get("RAVEN_JSON_LOG"):
        if log_target:
            log_target.parent.mkdir(parents=True, exist_ok=True)
            logger.add(str(log_target), level="DEBUG", format=_serialize, rotation="100 MB", retention="30 days")
            logger.add(
                str(log_target.with_suffix(".err.log")),
                level="WARNING",
                format=_serialize,
                rotation="100 MB",
                retention="90 days",
            )
        console_fmt = "{time:HH:mm:ss} | {level: <8} | {name} - {message}"
    else:
        console_fmt = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>"

    logger.add(sys.stderr, level=log_level, format=console_fmt, colorize=not (json_format or os.environ.get("RAVEN_JSON_LOG")))

    logger.info("Logging initialized (json={}, level={})", json_format, log_level)

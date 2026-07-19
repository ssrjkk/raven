from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import SecretStr

from raven.core._json import json

correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")

_CONTEXT_BINDINGS: ContextVar[dict[str, Any]] = ContextVar("context_bindings", default={})  # noqa: B039


def bind_context(**kwargs: Any) -> None:
    ctx = _CONTEXT_BINDINGS.get().copy()
    ctx.update(kwargs)
    _CONTEXT_BINDINGS.set(ctx)


def unbind_context(*keys: str) -> None:
    ctx = _CONTEXT_BINDINGS.get().copy()
    for k in keys:
        ctx.pop(k, None)
    _CONTEXT_BINDINGS.set(ctx)


def clear_context() -> None:
    _CONTEXT_BINDINGS.set({})


def get_context() -> dict[str, Any]:
    return dict(_CONTEXT_BINDINGS.get())


def _mask_secret_str(record):
    args = record.get("args")
    if args is not None and isinstance(args, tuple):
        masked = []
        for arg in args:
            if isinstance(arg, SecretStr):
                masked.append("**********")
            else:
                masked.append(arg)
        record["args"] = tuple(masked)
    return True


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
    ctx = get_context()
    if ctx:
        subset["context"] = ctx
    exception = record.get("exception")
    if exception:
        subset["exception"] = str(exception)
    extra = {k: v for k, v in record["extra"].items() if k not in ("correlation_id", "extra")}
    if extra:
        subset["extra"] = extra
    return json.dumps(subset, default=str)


try:
    import structlog as _structlog

    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


def _structlog_processors(json_format: bool) -> list[Callable[..., Any]]:
    processors: list[Callable[..., Any]] = [
        _structlog.contextvars.merge_contextvars,
        _structlog.processors.add_log_level,
        _structlog.processors.StackInfoRenderer(),
        _structlog.dev.set_exc_info,
        _structlog.processors.TimeStamper(fmt="iso"),
    ]
    if json_format:
        processors.append(_structlog.processors.JSONRenderer())
    else:
        processors.append(_structlog.dev.ConsoleRenderer())
    return processors


def setup_logging(log_file: str | Path | None = None, level: str = "INFO", json_format: bool = True):
    logger.remove()
    log_level = level.upper()
    log_path = Path(log_file) if log_file else None
    file_path = os.environ.get("RAVEN_LOG_FILE")

    log_target = log_path or (Path(file_path) if file_path else None)
    if json_format or os.environ.get("RAVEN_JSON_LOG"):
        if log_target:
            log_target.parent.mkdir(parents=True, exist_ok=True)
            logger.add(str(log_target), level="DEBUG", format=_serialize, rotation="100 MB", retention="30 days", filter=_mask_secret_str)
            logger.add(
                str(log_target.with_suffix(".err.log")),
                level="WARNING",
                format=_serialize,
                rotation="100 MB",
                retention="90 days",
                filter=_mask_secret_str,
            )
        console_fmt = "{time:HH:mm:ss} | {level: <8} | {name} - {message}"
    else:
        console_fmt = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - <level>{message}</level>"

    logger.add(sys.stderr, level=log_level, format=console_fmt, colorize=not (json_format or os.environ.get("RAVEN_JSON_LOG")), filter=_mask_secret_str)

    if HAS_STRUCTLOG:
        import logging as _stdlib_logging
        _structlog.configure(
            processors=_structlog_processors(json_format or bool(os.environ.get("RAVEN_JSON_LOG"))),
            wrapper_class=_structlog.make_filtering_bound_logger(getattr(_stdlib_logging, log_level, _stdlib_logging.INFO)),
            context_class=dict,
            logger_factory=_structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=False,
        )

    logger.info("Logging initialized (json={}, level={})", json_format, log_level)

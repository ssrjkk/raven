from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import SecretStr

from raven.core._json import json

if TYPE_CHECKING:
    from loguru import Record

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


def _mask_secret_str(record: Any) -> bool:
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


def _attach_correlation_id(record: Record) -> None:
    record["extra"].setdefault("correlation_id", correlation_id.get())


def _enrich_record(record: Record) -> bool:
    _attach_correlation_id(record)
    return _mask_secret_str(record)


def _enrich_and_serialize(record: Record) -> bool:
    """Sink filter that also builds the JSON line.

    loguru uses the return value of a callable `format` as a *template* and runs `format_map` on
    it, so handing it `_serialize`'s output raised `KeyError: '\"timestamp\"'` and dropped every
    record. The JSON has to travel in the record instead, and a filter's mutation of
    `record["extra"]` is visible to the handler's format.
    """
    _enrich_record(record)
    record["extra"]["json_line"] = _serialize(record)
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


_CONSOLE_FMT = "{time:HH:mm:ss} | {level: <8} | {name} - {message}"
_FILE_FMT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
_CONSOLE_COLOR_FMT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> - <level>{message}</level>"
)


def setup_logging(log_file: str | Path | None = None, level: str | None = None, json_format: bool | None = None):
    from raven.core.config import settings

    logger.remove()
    log_level = (level or settings.log_level).upper()
    as_json = settings.json_log if json_format is None else json_format
    target = Path(log_file) if log_file else settings.resolved_log_file
    target.parent.mkdir(parents=True, exist_ok=True)

    file_fmt = "{extra[json_line]}" if as_json else _FILE_FMT
    file_filter = _enrich_and_serialize if as_json else _enrich_record
    logger.add(
        str(target),
        level="DEBUG",
        format=file_fmt,
        encoding="utf-8",
        rotation="100 MB",
        retention="30 days",
        filter=file_filter,
    )
    logger.add(
        str(target.with_suffix(".err.log")),
        level="WARNING",
        format=file_fmt,
        encoding="utf-8",
        rotation="100 MB",
        retention="90 days",
        filter=file_filter,
    )
    console_fmt = _CONSOLE_FMT if as_json else _CONSOLE_COLOR_FMT

    logger.add(
        sys.stderr,
        level=log_level,
        format=console_fmt,
        colorize=not as_json,
        filter=_enrich_record,
    )

    if HAS_STRUCTLOG:
        import logging as _stdlib_logging

        _structlog.configure(
            processors=_structlog_processors(as_json),
            wrapper_class=_structlog.make_filtering_bound_logger(
                getattr(_stdlib_logging, log_level, _stdlib_logging.INFO)
            ),
            context_class=dict,
            logger_factory=_structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=False,
        )

    logger.info("Logging initialized (json={}, level={})", as_json, log_level)

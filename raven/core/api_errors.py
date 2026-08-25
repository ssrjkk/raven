from __future__ import annotations

from fastapi import HTTPException
from loguru import logger


def internal_error(exc: Exception) -> HTTPException:
    logger.error("[api] internal error: {}: {}", type(exc).__name__, exc)
    return HTTPException(500, f"Internal error: {type(exc).__name__}")

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    CONFIG_MISSING = "config.missing"
    AUTH_DENIED = "auth.denied"
    RATE_LIMITED = "rate.limited"
    NOT_FOUND = "resource.not_found"
    VALIDATION = "validation.error"
    LLM_ERROR = "llm.error"
    LLM_TIMEOUT = "llm.timeout"
    LLM_RATE_LIMIT = "llm.rate_limit"
    CHANNEL_ERROR = "channel.error"
    CHANNEL_DISCONNECTED = "channel.disconnected"
    DATABASE_ERROR = "database.error"
    PLUGIN_ERROR = "plugin.error"
    SANDBOX_ERROR = "sandbox.error"
    TIMEOUT = "timeout"
    INTERNAL = "internal.error"
    WEBHOOK_FAILED = "webhook.failed"
    CIRCUIT_OPEN = "circuit.open"
    QUOTA_EXCEEDED = "quota.exceeded"
    UPSTREAM_ERROR = "upstream.error"


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str = "", detail: Any = None, retryable: bool = False):
        self.code = code
        self.message = message or code.value
        self.detail = detail
        self.retryable = retryable
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code.value, "message": self.message, "detail": self.detail, "retryable": self.retryable}


class ConfigError(AppError):
    def __init__(self, key: str, message: str = ""):
        super().__init__(ErrorCode.CONFIG_MISSING, message or f"Missing config: {key}", detail={"key": key})


class AuthError(AppError):
    def __init__(self, message: str = "Access denied", detail: Any = None):
        super().__init__(ErrorCode.AUTH_DENIED, message, detail)


class LLMError(AppError):
    def __init__(self, message: str = "LLM call failed", detail: Any = None, retryable: bool = True):
        super().__init__(ErrorCode.LLM_ERROR, message, detail, retryable)


class ChannelError(AppError):
    def __init__(self, channel: str, message: str = "", detail: Any = None):
        super().__init__(ErrorCode.CHANNEL_ERROR, message or f"Channel {channel} error", detail={"channel": channel})


def classify_error(e: Exception) -> AppError:
    if isinstance(e, AppError):
        return e
    msg = str(e)
    if "timeout" in msg.lower():
        return AppError(ErrorCode.TIMEOUT, msg, retryable=True)
    if "rate limit" in msg.lower() or "too many requests" in msg.lower() or "429" in msg:
        return AppError(ErrorCode.RATE_LIMITED, msg, retryable=True)
    if "not found" in msg.lower() or "404" in msg:
        return AppError(ErrorCode.NOT_FOUND, msg)
    if "auth" in msg.lower() or "unauthorized" in msg.lower() or "403" in msg:
        return AppError(ErrorCode.AUTH_DENIED, msg)
    if "connection" in msg.lower() or "disconnect" in msg.lower() or "refused" in msg.lower():
        return AppError(ErrorCode.UPSTREAM_ERROR, msg, retryable=True)
    return AppError(ErrorCode.INTERNAL, msg)

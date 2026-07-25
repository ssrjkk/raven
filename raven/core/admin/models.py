from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

_SSRF_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]", "169.254.169.254", "metadata.google.internal"}


def _check_ssrf(target: str) -> str:
    if target.startswith(("http://", "https://")):
        parsed = urlparse(target)
        if parsed.hostname and parsed.hostname.lower() in _SSRF_BLOCKED_HOSTS:
            msg = f"SSRF protection: target host '{parsed.hostname}' is forbidden"
            raise ValueError(msg)
    return target


class MonitorConditionRequest(BaseModel):
    metric: str = Field(default="", max_length=100)
    operator: str = Field(default="=", pattern=r"^(=|>|<|>=|<=|!=|contains|matches)$")
    value: float | str | None = None


class MonitorCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[\w\-\s]+$")
    type: Literal["http", "price", "rss", "file", "process"] = "http"
    target: str = Field(..., min_length=1, max_length=500)
    interval_seconds: int = Field(default=300, ge=10, le=86400)
    status: str = Field(default="active", pattern=r"^(active|paused)$")
    conditions: list[MonitorConditionRequest] = Field(default_factory=list)
    user_id: str = Field(default="", max_length=100)
    channel: str = Field(default="", max_length=100)
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        return _check_ssrf(v)


class MonitorUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: Literal["http", "price", "rss", "file", "process"] | None = None
    target: str | None = Field(default=None, min_length=1, max_length=500)
    interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    status: str | None = Field(default=None, pattern=r"^(active|paused)$")
    conditions: list[MonitorConditionRequest] | None = None
    user_id: str | None = Field(default=None, max_length=100)
    channel: str | None = Field(default=None, max_length=100)
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)
    config: dict[str, Any] | None = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str | None) -> str | None:
        if v is not None:
            return _check_ssrf(v)
        return v


class ConfigUpdateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: str = Field(..., min_length=1, max_length=5000)


class SecretRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=10000)


class AuthLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=256)


class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100, pattern=r"^[\w@\.\-]+$")
    password: str = Field(..., min_length=6, max_length=256)
    display_name: str | None = Field(default=None, max_length=100)


class AuthUpdateRoleRequest(BaseModel):
    role: Literal["admin", "user", "viewer", "banned"]


class SSEPushRequest(BaseModel):
    event: str = Field(default="message", max_length=100)
    data: dict[str, Any] = Field(default_factory=dict)
    session: str | None = Field(default=None, max_length=100)

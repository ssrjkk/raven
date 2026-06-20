from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class Permission(enum.Enum):
    CHAT = "chat"
    TASK_RUN = "task:run"
    TASK_LIST = "task:list"
    MONITOR_READ = "monitor:read"
    MONITOR_WRITE = "monitor:write"
    ROUTINE_READ = "routine:read"
    ROUTINE_WRITE = "routine:write"
    CODE_READ = "code:read"
    CODE_WRITE = "code:write"
    ADMIN_READ = "admin:read"
    ADMIN_WRITE = "admin:write"
    ADMIN_USERS = "admin:users"
    ADMIN_SECRETS = "admin:secrets"
    SYSTEM_SHUTDOWN = "system:shutdown"


class Role(enum.StrEnum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"
    BANNED = "banned"


ROLE_PERMISSIONS: dict[Role, list[Permission]] = {
    Role.ADMIN: list(Permission),
    Role.USER: [
        Permission.CHAT,
        Permission.TASK_RUN,
        Permission.TASK_LIST,
        Permission.MONITOR_READ,
        Permission.MONITOR_WRITE,
        Permission.ROUTINE_READ,
        Permission.ROUTINE_WRITE,
        Permission.CODE_READ,
        Permission.CODE_WRITE,
    ],
    Role.VIEWER: [
        Permission.CHAT,
        Permission.TASK_LIST,
        Permission.MONITOR_READ,
        Permission.ROUTINE_READ,
        Permission.CODE_READ,
    ],
    Role.BANNED: [],
}


class User(BaseModel):
    id: str
    username: str
    display_name: str = ""
    role: Role = Role.USER
    password_hash: str = ""
    api_tokens: list[str] = []
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AuthSession(BaseModel):
    token: str
    user_id: str
    role: Role
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime

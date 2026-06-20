from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"
    IMPORT = "import"
    CONSTANT = "constant"
    INTERFACE = "interface"
    TYPE = "type"


class CodeFile(BaseModel):
    path: str = ""
    language: str = ""
    size: int = 0
    lines: int = 0
    modified_at: float = 0.0
    symbols: list[CodeSymbol] = Field(default_factory=list)
    content_preview: str = ""


class CodeSymbol(BaseModel):
    name: str = ""
    kind: SymbolKind = SymbolKind.FUNCTION
    line: int = 0
    column: int = 0
    docstring: str = ""
    signature: str = ""


class SessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class CodingSession(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    channel: str = ""
    goal: str = ""
    project_path: str = ""
    files: list[str] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=lambda: time.time())
    updated_at: float = Field(default_factory=lambda: time.time())


class ReviewSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"
    PRAISE = "praise"


class ReviewComment(BaseModel):
    file: str = ""
    line: int = 0
    severity: ReviewSeverity = ReviewSeverity.WARNING
    message: str = ""
    suggestion: str = ""

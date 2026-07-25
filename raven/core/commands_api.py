from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel


class CommandResponse(BaseModel):
    id: str
    label: str
    description: str
    icon: str  # 'code', 'db', 'file'
    category: str
    action_endpoint: str | None = None


def _detect_project_state() -> str:
    workspace = Path(os.getenv("RAVEN_WORKSPACE", "workspace"))
    if not workspace.is_dir():
        return "empty"
    try:
        py = list(workspace.rglob("*.py"))
        ts = list(workspace.rglob("*.ts"))
        tsx = list(workspace.rglob("*.tsx"))
        rs = list(workspace.rglob("*.rs"))
        go = list(workspace.rglob("*.go"))
    except PermissionError:
        return "has_code"
    total = len(py) + len(ts) + len(tsx) + len(rs) + len(go)
    return "empty" if total == 0 else "has_code"


def create_commands_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/commands", tags=["commands"])

    @router.get("/contextual", response_model=list[CommandResponse])
    async def get_contextual_commands():
        project_state = _detect_project_state()

        commands: list[CommandResponse] = []

        if project_state == "empty":
            commands.append(
                CommandResponse(
                    id="scaffold-api",
                    label="Создать FastAPI структуру",
                    description="Сгенерировать boilerplate для нового API",
                    icon="code",
                    category="ai",
                    action_endpoint="/api/v1/ai/scaffold",
                )
            )

        commands.append(
            CommandResponse(
                id="generate-tests",
                label="Сгенерировать тесты",
                description="AI напишет unit-тесты для текущих модулей",
                icon="code",
                category="ai",
                action_endpoint="/api/v1/ai/generate-tests",
            )
        )

        return commands

    return router

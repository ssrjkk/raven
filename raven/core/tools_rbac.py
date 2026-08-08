from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


class ToolPolicyStore:
    """Persistent role→tool overrides stored in data/tool_policy.json.

    Schema: {"<tool_name>": ["role1", "role2"]}. An entry overrides the tool's
    default `allowed_roles` (and the dangerous→admin fallback) without a restart.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            try:
                from raven.core.config import settings

                path = settings.resolved_data_dir / "tool_policy.json"
            except Exception:
                path = Path("data/tool_policy.json")
        self._path = Path(path)
        self._policy: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open() as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._policy = {
                    str(k): [str(r) for r in v]
                    for k, v in raw.items()
                    if isinstance(v, list)
                }
        except Exception as e:
            logger.warning("Failed to load tool policy: {}", e)

    def get(self, tool_name: str) -> list[str] | None:
        roles = self._policy.get(tool_name)
        return list(roles) if roles is not None else None

    def set(self, tool_name: str, roles: list[str]) -> None:
        self._policy[tool_name] = list(roles)

    def remove(self, tool_name: str) -> None:
        self._policy.pop(tool_name, None)

    def all(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._policy.items()}

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w") as f:
                json.dump(self._policy, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning("Failed to persist tool policy: {}", e)

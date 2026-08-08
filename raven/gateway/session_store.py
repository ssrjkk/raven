from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from raven.core._json import json

if TYPE_CHECKING:
    from raven.gateway.daemon import FlowSession


class SessionStore:
    """JSON-file persistence for FlowSession metadata (agent is not serialized)."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "sessions"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def directory(self) -> Path:
        return self._dir

    def save(self, session: FlowSession) -> None:
        payload = json.dumps(session.to_dict())
        target = self._dir / f"{session.id}.json"
        fd, tmp_name = tempfile.mkstemp(prefix=f"{session.id}-", suffix=".tmp", dir=self._dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            Path(tmp_name).replace(target)
        except Exception:
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink()
            raise

    def load_all(self) -> list[FlowSession]:
        from raven.gateway.daemon import FlowSession

        sessions: list[FlowSession] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("SessionStore: corrupt file {}, skipping: {}", path.name, exc)
                continue
            session = FlowSession.from_dict(data)
            if session is None:
                logger.warning("SessionStore: invalid payload in {}, skipping", path.name)
                continue
            sessions.append(session)
        return sessions

    def remove(self, session_id: str) -> None:
        target = self._dir / f"{session_id}.json"
        target.unlink(missing_ok=True)

    def prune(self, max_age_seconds: int) -> int:
        now = time.time()
        removed = 0
        for path in self._dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime > max_age_seconds:
                try:
                    path.unlink()
                    removed += 1
                except OSError as exc:
                    logger.warning("SessionStore: failed to prune {}: {}", path.name, exc)
        return removed

    def count(self) -> int:
        return len(list(self._dir.glob("*.json")))

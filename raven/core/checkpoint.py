from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from raven.core.db import Database


@dataclass
class SessionCheckpoint:
    session_id: str
    channel: str
    messages: list[dict[str, object]]
    agent_state: dict[str, object]
    created_at: str


class CheckpointManager:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, session_id: str, messages: list[dict[str, object]], agent_state: dict[str, object]) -> str:
        import json
        from uuid import uuid4

        checkpoint_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        serialized_messages = json.dumps(
            [m if isinstance(m, dict) else {"role": m.role, "content": m.content} for m in messages]
        )
        await self._db.conn.execute(
            "INSERT INTO checkpoints (id, session_id, channel, messages, agent_state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (checkpoint_id, session_id, "", serialized_messages, json.dumps(agent_state), now),
        )
        await self._db.conn.commit()
        return checkpoint_id

    async def load(self, checkpoint_id: str) -> SessionCheckpoint | None:
        import json

        async with self._db.conn.execute(
            "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ) as c:
            row = await c.fetchone()
        if not row:
            return None
        return SessionCheckpoint(
            session_id=row["session_id"],
            channel=row["channel"],
            messages=json.loads(row["messages"]),
            agent_state=json.loads(row["agent_state"]),
            created_at=row["created_at"],
        )

    async def list_checkpoints(self, session_id: str) -> list[SessionCheckpoint]:
        import json

        async with self._db.conn.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC", (session_id,)
        ) as c:
            rows = await c.fetchall()
        return [
            SessionCheckpoint(
                session_id=row["session_id"],
                channel=row["channel"],
                messages=json.loads(row["messages"]),
                agent_state=json.loads(row["agent_state"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def delete(self, checkpoint_id: str) -> None:
        await self._db.conn.execute("DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,))
        await self._db.conn.commit()

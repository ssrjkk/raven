from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from ravencode.core.prompts import get_prompt

# ---------------------------------------------------------------------------
# memory store
# ---------------------------------------------------------------------------


@dataclass
class MemoryStore:
    path: str = "data/ravencode_memory.json"
    _data: dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _bg_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    _flush_task: asyncio.Task[None] | None = field(default=None)
    _flush_pending: bool = field(default=False)

    def __post_init__(self):
        p = Path(self.path).expanduser().resolve()
        if p.exists():
            try:
                self._data = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            return self._data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = value
        await self._persist()

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)
        await self._persist()

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()
        await self._persist()

    async def keys(self) -> list[str]:
        async with self._lock:
            return list(self._data.keys())

    def _write(self, snapshot: dict[str, Any]) -> None:
        p = Path(self.path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    async def _persist(self) -> None:
        async with self._lock:
            snapshot = dict(self._data)
        await asyncio.to_thread(self._write, snapshot)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._schedule_flush()

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_pending = True
            return
        self._flush_pending = False
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._bg_tasks.add(self._flush_task)
        self._flush_task.add_done_callback(self._bg_tasks.discard)

    async def _flush_loop(self) -> None:
        while True:
            async with self._lock:
                snapshot = dict(self._data)
                pending = self._flush_pending
                self._flush_pending = False
            await asyncio.to_thread(self._write, snapshot)
            if not pending:
                return

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


# ---------------------------------------------------------------------------
# system prompt loader
# ---------------------------------------------------------------------------


def load_system_prompt_from_file(path: str | Path | None = None) -> str | None:
    candidates = [
        Path(path).expanduser().resolve() if path else None,
        Path.cwd() / "AGENTS.md",
        Path.cwd() / ".opencode" / "AGENTS.md",
        Path.home() / ".config" / "opencode" / "AGENTS.md",
    ]
    for c in candidates:
        if c and c.is_file():
            try:
                return c.read_text(encoding="utf-8")
            except OSError:
                continue
    return None


# ---------------------------------------------------------------------------
# conversation
# ---------------------------------------------------------------------------


class Conversation:
    def __init__(
        self,
        system_prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        max_tokens: int = 128_000,
        memory: MemoryStore | None = None,
    ) -> None:
        self.system_prompt = system_prompt or load_system_prompt_from_file() or self._default_system_prompt()
        self.messages: list[dict[str, Any]] = messages or []
        self.max_tokens = max_tokens
        self.memory = memory or MemoryStore()

        if not self.messages or self.messages[0].get("role") != "system":
            self.messages.insert(0, {"role": "system", "content": self.system_prompt})
        self._token_total = self._total_tokens()

    @property
    def message_count(self) -> int:
        return max(0, len(self.messages) - 1)

    # -------------------------------------------------------------------
    # message management
    # -------------------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def get_messages(self) -> list[dict[str, Any]]:
        return self.messages

    # -------------------------------------------------------------------
    # trimming (rough token estimate)
    # -------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4 + len(text.split())

    def _total_tokens(self) -> int:
        total = 0
        for msg in self.messages:
            if isinstance(msg.get("content"), str):
                total += self._estimate_tokens(msg["content"])
        return total

    def _trim(self) -> None:
        while len(self.messages) > 2 and self._token_total > self.max_tokens:
            popped = self.messages.pop(1)
            content = popped.get("content")
            if isinstance(content, str):
                self._token_total -= self._estimate_tokens(content)

    async def summarize_oldest(self, llm: Any | None = None) -> None:
        if len(self.messages) < 4:
            return
        idx = 1
        if self.messages[idx].get("role") in ("system",):
            idx = 2
        if idx >= len(self.messages):
            return
        oldest = self.messages[idx]
        if llm is None:
            self.messages.pop(idx)
            self._token_total -= self._estimate_tokens(str(oldest.get("content", "")))
            return
        try:
            summary_prompt = (
                "Summarize the following conversation exchange in 1-2 sentences, "
                "preserving all key facts, decisions, and context:\n\n"
                f"{json.dumps(oldest, ensure_ascii=False)}"
            )
            resp = await llm.complete(
                messages=[{"role": "user", "content": summary_prompt}],
                model="",
                tools=None,
            )
            summary = resp.content.strip() if resp.content else ""
            if summary:
                self._token_total -= self._estimate_tokens(str(oldest.get("content", "")))
                self.messages[idx] = {"role": "user", "content": f"[summarized] {summary}"}
                self._token_total += self._estimate_tokens(f"[summarized] {summary}")
                logger.debug(
                    "Context summarization: compressed {} chars -> {} chars",
                    len(oldest.get("content", "")),
                    len(summary),
                )
        except Exception as e:
            logger.warning("Context summarization failed, dropping oldest message: {}", e)
            self.messages.pop(idx)
            self._token_total -= self._estimate_tokens(str(oldest.get("content", "")))

    # -------------------------------------------------------------------
    # serialization
    # -------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "messages": self.messages,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        return cls(
            system_prompt=data.get("system_prompt"),
            messages=data.get("messages"),
            max_tokens=data.get("max_tokens", 128_000),
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return get_prompt("system")


# ---------------------------------------------------------------------------
# factory
# ---------------------------------------------------------------------------


def create_conversation(
    system_prompt: str | None = None,
    memory_path: str | None = None,
) -> Conversation:
    memory = MemoryStore(path=memory_path) if memory_path else None
    return Conversation(system_prompt=system_prompt, memory=memory)

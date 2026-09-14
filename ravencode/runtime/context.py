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

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.lower().split())

    async def push(self, key: str, item: str, max_items: int = 20) -> bool:
        """Append to a list with near-duplicate removal and a hard cap.

        Case/whitespace-insensitive dedup keeps the memory meaningful over
        long sessions: repeating "fixed the parser bug" ten times must not
        crowd out anything else. Returns True when the item was new.
        """
        async with self._lock:
            lst = self._data.get(key)
            if isinstance(lst, str) and lst.strip():
                lst = [lst]  # scalar → list, preserving the previous value
            elif not isinstance(lst, list):
                lst = []
            norm = self._normalize(str(item))
            if not norm:
                return False
            if any(isinstance(x, str) and self._normalize(x) == norm for x in lst):
                return False
            lst.append(str(item))
            self._data[key] = lst[-max_items:]
        await self._persist()
        return True

    async def compact_lists(self, max_items: int = 20) -> int:
        """Deduplicate and cap every list stored in memory. Returns removed count."""
        async with self._lock:
            removed = 0
            for key, value in list(self._data.items()):
                if not isinstance(value, list):
                    continue
                seen: set[str] = set()
                kept: list[Any] = []
                for item in value:
                    norm = self._normalize(str(item)) if isinstance(item, str) else json.dumps(item, sort_keys=True)
                    if norm in seen:
                        removed += 1
                        continue
                    seen.add(norm)
                    kept.append(item)
                if len(kept) > max_items:
                    removed += len(kept) - max_items
                    kept = kept[-max_items:]
                self._data[key] = kept
        await self._persist()
        return removed

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

    @property
    def token_total(self) -> int:
        return self._token_total

    # -------------------------------------------------------------------
    # message management
    # -------------------------------------------------------------------

    def add_user_message(self, content: str | list[dict[str, Any]]) -> None:
        self.messages.append({"role": "user", "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def add_system_message(self, content: str) -> None:
        self.messages.append({"role": "system", "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._token_total += self._estimate_tokens(content)
        self._trim()

    def add_assistant_tool_calls(self, tool_calls: list[dict[str, Any]], content: str = "") -> None:
        """Record an assistant turn that requests tools.

        Required by the OpenAI-compatible chat protocol: every ``role: tool``
        message must be preceded by an assistant message carrying the matching
        ``tool_calls`` (otherwise providers such as Groq/OpenAI reject the
        request with HTTP 400).
        """
        self.messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})
        if content:
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

    def _estimate_tokens(self, text: str | list[dict[str, Any]]) -> int:
        if isinstance(text, str):
            return len(text) // 4 + len(text.split())
        total = 0
        for block in text:
            if not isinstance(block, dict):
                continue
            payload = block.get("text") or block.get("image_url")
            if isinstance(payload, dict):
                payload = payload.get("url", "")
            total += self._estimate_tokens(str(payload))
        return total

    def _total_tokens(self) -> int:
        total = 0
        for msg in self.messages:
            content = msg.get("content")
            if isinstance(content, (str, list)):
                total += self._estimate_tokens(content)
        return total

    def compact(self, keep_recent: int = 12) -> int:
        """Compress old tool results to relieve context pressure.

        Runs before hard trimming: instead of losing whole messages, older
        tool outputs are replaced with short prefixes so the model keeps a
        coherent recent window. Returns estimated tokens saved.
        """
        threshold = int(self.max_tokens * 0.7)
        if self._token_total <= threshold:
            return 0
        saved = 0
        for msg in self.messages[1:-keep_recent] if keep_recent < len(self.messages) else []:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content")
            if not isinstance(content, str) or len(content) <= 800:
                continue
            compressed = (
                content[:800]
                + "\n[... older tool output compressed to save context; re-run the tool if you need it again ...]"
            )
            saved += self._estimate_tokens(content) - self._estimate_tokens(compressed)
            msg["content"] = compressed
        if saved:
            self._token_total -= saved
            logger.debug("Context compaction: saved ~{} tokens from old tool results", saved)
        return saved

    def compact_deep(self, keep_recent: int = 8) -> int:
        """Second-stage compaction: replace the old tail with a rolling digest.

        When tool-result compression is not enough (very long sessions), the
        non-recent conversation is collapsed into a single deterministic
        digest message that preserves the narrative: what the user asked,
        what the assistant decided, which tools ran (names + arg summaries).
        No LLM call needed, so it is safe to run mid-loop. Returns the number
        of dropped messages.
        """
        if len(self.messages) <= keep_recent + 1:
            return 0
        dropped = self.messages[1:-keep_recent]
        if not dropped:
            return 0
        digest_lines: list[str] = ["[conversation digest — older turns condensed]"]
        for msg in dropped:
            role = msg.get("role")
            content = msg.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False) if content else ""
            text = " ".join(str(text).split())
            tool_calls = msg.get("tool_calls") or []
            if role == "user":
                if text:
                    digest_lines.append(f"user: {text[:200]}")
            elif role == "assistant":
                if tool_calls:
                    names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    digest_lines.append(f"assistant: called tools {', '.join(names)}")
                elif text:
                    digest_lines.append(f"assistant: {text[:200]}")
            elif role == "system" and text:
                digest_lines.append(f"note: {text[:150]}")
            # role == "tool": represented by the assistant tool-call line above
        digest = "\n".join(digest_lines)
        self.messages = [
            self.messages[0],
            {"role": "user", "content": digest},
            *self.messages[-keep_recent:],
        ]
        self._token_total = self._total_tokens()
        self._drop_orphan_tool_messages()
        logger.info("Deep compaction: {} messages → digest ({} chars)", len(dropped), len(digest))
        return len(dropped)

    def _trim(self) -> None:
        popped_any = False
        while len(self.messages) > 2 and self._token_total > self.max_tokens:
            popped = self.messages.pop(1)
            popped_any = True
            content = popped.get("content")
            if isinstance(content, (str, list)):
                self._token_total -= self._estimate_tokens(content)
        if popped_any:
            # Popped messages may carry tokens outside ``content`` (e.g. a
            # tool_calls-only assistant turn) — recompute to avoid drift.
            self._token_total = self._total_tokens()
        self._drop_orphan_tool_messages()

    def _drop_orphan_tool_messages(self) -> None:
        """Remove ``role: tool`` messages whose requesting assistant turn was
        trimmed away. Providers reject tool results with no matching
        ``tool_calls`` assistant message."""
        cleaned: list[dict[str, Any]] = []
        pending_ids: set[str] = set()
        for msg in self.messages:
            role = msg.get("role")
            if role == "assistant":
                pending_ids = {tc.get("id") for tc in (msg.get("tool_calls") or [])}
                cleaned.append(msg)
            elif role == "tool":
                tcid = msg.get("tool_call_id")
                if tcid in pending_ids:
                    pending_ids.discard(tcid)
                    cleaned.append(msg)
            else:
                pending_ids = set()
                cleaned.append(msg)
        if len(cleaned) != len(self.messages):
            self.messages = cleaned
            self._token_total = self._total_tokens()

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

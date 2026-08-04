from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from raven.core.llm import LLMRouter


@dataclass
class ContextWindowConfig:
    max_tokens: int = 128000
    warning_threshold: float = 0.8
    summarization_threshold: float = 0.9
    hard_limit_threshold: float = 0.95
    reserved_tokens: int = 2000
    sliding_window_size: int = 20


class ContextWindowManager:
    def __init__(self, llm: LLMRouter, config: ContextWindowConfig | None = None) -> None:
        self._llm = llm
        self._config = config or ContextWindowConfig()

    def _count_tokens_estimate(self, text: str) -> int:
        if not text:
            return 0
        words = len(text.split())
        cjk = sum(1 for ch in text if "\u2e80" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff")
        est = words + (len(text) - cjk) / 4 + cjk * 1.5
        return max(1, int(est))

    async def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "") or ""
            total += self._count_tokens_estimate(str(content)) + 10
        return total

    async def summarize_messages(self, messages: list[dict[str, Any]], llm: LLMRouter | None = None) -> str:
        router = llm or self._llm
        history = "\n".join(f"{m.get('role', '?')}: {(str(m.get('content', ''))[:500])}" for m in messages)
        prompt = (
            "Summarize the following conversation history in 2-3 concise sentences. "
            "Preserve all key facts, decisions, user requirements, constraints, and partial work.\n\n"
            f"History:\n{history}"
        )
        try:
            resp = await router.complete(
                messages=[{"role": "user", "content": prompt}],
                model="",
                tools=None,
            )
            summary = resp.content.strip() if resp.content else ""
            return summary[:1000] if summary else ""
        except Exception as exc:
            logger.warning("Message summarization failed: {}", exc)
            return ""

    async def manage(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not messages:
            return messages

        total = await self.estimate_tokens(messages)
        ratio = total / self._config.max_tokens if self._config.max_tokens > 0 else 0

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if ratio < self._config.warning_threshold:
            return messages

        logger.info(
            "Context at {:.1f}% of token limit ({} / {})",
            ratio * 100,
            total,
            self._config.max_tokens,
        )

        if ratio <= self._config.summarization_threshold:
            note = {
                "role": "system",
                "content": (
                    f"[Note: Context usage is at {ratio * 100:.0f}%. "
                    "Please be concise in responses to conserve context.]"
                ),
            }
            return [*system_msgs, note, *non_system] if non_system else [*system_msgs, note]

        if ratio <= self._config.hard_limit_threshold:
            keep_count = min(self._config.sliding_window_size, len(non_system))
            batch = non_system[: max(0, len(non_system) - keep_count - 5)]
            if batch:
                summary_text = await self.summarize_messages(batch)
                if summary_text:
                    summary_msg: dict[str, Any] = {
                        "role": "system",
                        "content": f"[Summarized earlier context: {summary_text}]",
                    }
                    keep = non_system[-keep_count:] if keep_count > 0 else []
                    return [*system_msgs, summary_msg, *keep]
                logger.info("Summarization returned empty, dropping oldest batch")
            keep = non_system[-keep_count:] if keep_count > 0 else []
            return system_msgs + keep

        logger.warning(
            "Context at {:.1f}% — dropping oldest messages (hard limit)",
            ratio * 100,
        )
        keep_count = min(self._config.sliding_window_size, len(non_system))
        keep = non_system[-keep_count:] if keep_count > 0 else []
        return system_msgs + keep

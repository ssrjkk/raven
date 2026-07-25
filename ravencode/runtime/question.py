from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

_QUESTION_CALLBACK: Any = None


def set_question_callback(callback: Any) -> None:
    global _QUESTION_CALLBACK
    _QUESTION_CALLBACK = callback


class QuestionError(Exception):
    def __init__(self, question_data: dict[str, Any]) -> None:
        self.question_data = question_data
        super().__init__()


@dataclass
class Question:
    question: str
    header: str = ""
    options: list[dict[str, str]] = field(default_factory=list)
    multiple: bool = False


async def ask_question(q: Question) -> str:
    cb = _QUESTION_CALLBACK
    if cb is not None:
        result = await cb(q)
        if isinstance(result, str):
            return result
        return str(result)
    raise QuestionError(
        {
            "question": q.question,
            "header": q.header,
            "options": q.options,
            "multiple": q.multiple,
        }
    )


async def stdin_question_callback(q: Question) -> str:
    logger.info("")
    logger.info(f"  [Question] {q.question}")
    if q.options:
        for i, opt in enumerate(q.options, 1):
            desc = opt.get("description", "")
            line = f"  {i}. {opt['label']}"
            if desc:
                line += f"  ({desc})"
            logger.info(line)
        logger.info("  0. Type your own answer")
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(None, lambda: input("  Your choice (0/custom): ").strip())
    if q.options and answer.isdigit():
        idx = int(answer)
        if 1 <= idx <= len(q.options):
            return q.options[idx - 1]["label"]
    return answer

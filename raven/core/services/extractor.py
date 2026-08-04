from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")
_PHONE_RE = re.compile(r"\+?[\d\s\-().]{7,}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4}")

_LLM_EXTRACT_MIN_CHARS = 60


@dataclass(frozen=True)
class Entity:
    text: str
    label: str
    start: int
    end: int
    score: float


@dataclass
class ExtractorResult:
    entities: list[Entity]
    raw: dict[str, Any]


PATTERN_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", _EMAIL_RE),
    ("URL", _URL_RE),
    ("PHONE", _PHONE_RE),
    ("DATE", _DATE_RE),
]


class EntityExtractor:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self._llm = llm_provider

    async def extract(self, text: str, labels: list[str] | None = None) -> ExtractorResult:
        entities = self._extract_pattern(text, labels)
        if self._llm and len(text.strip()) >= _LLM_EXTRACT_MIN_CHARS:
            try:
                llm_entities = await self._extract_llm(text, labels)
                seen = {(e.text, e.label) for e in entities}
                for e in llm_entities:
                    key = (e.text, e.label)
                    if key not in seen:
                        entities.append(e)
                        seen.add(key)
            except Exception as exc:
                logger.debug("[extractor] LLM entity extraction failed: {}", exc)
        return ExtractorResult(entities=entities, raw={"total": len(entities)})

    def _extract_pattern(self, text: str, labels: list[str] | None = None) -> list[Entity]:
        entities: list[Entity] = []
        for label, pattern in PATTERN_RULES:
            if labels and label not in labels:
                continue
            for m in pattern.finditer(text):
                entities.append(Entity(
                    text=m.group(),
                    label=label,
                    start=m.start(),
                    end=m.end(),
                    score=1.0,
                ))
        return entities

    async def _extract_llm(self, text: str, labels: list[str] | None = None) -> list[Entity]:
        if not self._llm:
            return []
        prompt = "Extract named entities (PERSON, ORG, LOC, PRODUCT, EVENT) from the following text. "
        prompt += "Return one per line in format: LABEL|text\n\nText:\n" + text[:4000]
        result = await self._llm.complete([{"role": "user", "content": prompt}])
        content = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
        entities: list[Entity] = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            label, _, value = line.partition("|")
            label = label.strip().upper()
            value = value.strip()
            if label and value:
                idx = text.find(value)
                if idx >= 0:
                    entities.append(Entity(text=value, label=label, start=idx, end=idx + len(value), score=0.8))
        return entities

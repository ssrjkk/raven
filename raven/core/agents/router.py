from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from loguru import logger

CLASSIFICATION_PROMPT = """You are an intent classifier for a multi-agent coding system.
Analyze the user's request and determine the BEST agent profile to handle it.

Available profiles:
- **architect**: System design, architecture planning, codebase analysis, tech decisions. NEVER writes code.
- **planner**: Breaking goals into tasks, coordinating multiple agents, dependency planning.
- **coder**: Writing code, implementing features, refactoring, fixing lint errors.
- **reviewer**: Code review, running linters/tests, finding bugs, quality check.
- **debugger**: Diagnosing bugs, reading stack traces, fixing runtime errors.
- **qa**: Running tests, writing test cases, validating coverage, integration testing.

Respond with ONLY the profile name and a confidence score 0-1, no explanation.
Format: profile_name|confidence

Examples:
"design a new authentication module" → architect|0.95
"fix the login bug" → debugger|0.9
"write unit tests for the API" → qa|0.95
"implement a user profile page" → coder|0.9
"review my latest commit" → reviewer|0.95
"what's the project structure?" → architect|0.8
"create a plan for migrating to postgres" → planner|0.9
"help me understand this error" → debugger|0.85
"add input validation" → coder|0.7
"""


@dataclass
class ClassificationResult:
    profile: str
    confidence: float
    raw_query: str


_KEYWORD_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"(?:design|architect|architecture|structure|overview|diagram|system\s*design)"), "architect", 0.7),
    (re.compile(r"(?:plan|break\s*down|decompose|roadmap|milestone|task\s*list|steps? to)"), "planner", 0.7),
    (re.compile(r"(?:debug|bug|error|crash|exception|stack.?trace|fix\s*this|not\s*working|broken|failing)"), "debugger", 0.8),
    (re.compile(r"(?:review|audit|check\s*code|quality|lint|code\s*review|static\s*analysis)"), "reviewer", 0.75),
    (re.compile(r"(?:test|coverage|unit\s*test|integration\s*test|e2e\s*test|pytest|assert)"), "qa", 0.75),
    (re.compile(r"(?:implement|write\s*code|create\s*(?:a|an)\s+(?:function|class|module|file)|refactor|add\s+feature)"), "coder", 0.65),
    (re.compile(r"(?:write|create|generate|build|make|develop)"), "coder", 0.5),
]


def _keyword_classify(text: str) -> ClassificationResult | None:
    lower = text.lower()
    best: tuple[str, float] | None = None
    for pattern, profile, score in _KEYWORD_RULES:
        if pattern.search(lower) and (best is None or score > best[1]):
            best = (profile, score)
    if best:
        return ClassificationResult(profile=best[0], confidence=best[1], raw_query=text)
    return None


class IntentRouter:
    def __init__(self, llm: Any):
        self._llm = llm

    async def classify(self, text: str, fallback_profile: str = "coder") -> ClassificationResult:
        keyword_result = _keyword_classify(text)
        if keyword_result is not None:
            logger.debug("IntentRouter: keyword match → {} ({})", keyword_result.profile, keyword_result.confidence)

        try:
            result = await self._llm.complete(
                [
                    {"role": "system", "content": CLASSIFICATION_PROMPT},
                    {"role": "user", "content": text},
                ],
                model="",  # use default
            )
            raw = (result.content or "").strip()
            if "|" in raw:
                parts = raw.rsplit("|", 1)
                profile = parts[0].strip().lower()
                try:
                    confidence = float(parts[1].strip())
                except (ValueError, IndexError):
                    confidence = 0.5
                if profile in ("architect", "planner", "coder", "reviewer", "debugger", "qa"):
                    llm_result = ClassificationResult(profile=profile, confidence=confidence, raw_query=text)
                    if keyword_result and keyword_result.profile == profile:
                        return llm_result
                    if keyword_result and llm_result.confidence >= 0.6:
                        return llm_result
                    if not keyword_result and llm_result.confidence >= 0.6:
                        return llm_result
        except Exception as e:
            logger.warning("IntentRouter: LLM classification failed: {}", e)

        if keyword_result:
            return keyword_result
        return ClassificationResult(profile=fallback_profile, confidence=0.5, raw_query=text)

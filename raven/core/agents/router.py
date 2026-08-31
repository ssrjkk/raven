from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
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
- **researcher**: Information gathering, codebase exploration, web research, knowledge discovery.
- **security**: Security auditing, vulnerability scanning, threat modeling, OWASP review.

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
"research the codebase for deprecated APIs" → researcher|0.9
"audit this code for security issues" → security|0.95
"""


@dataclass
class ClassificationResult:
    profile: str
    confidence: float
    raw_query: str


@dataclass
class ProfileOutcome:
    successes: int = 0
    failures: int = 0
    last_used: float = 0.0
    recent_results: list[bool] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 0.5

    def record(self, success: bool) -> None:
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self.last_used = time.monotonic()
        self.recent_results.append(success)
        if len(self.recent_results) > 10:
            self.recent_results.pop(0)


class FeedbackLoop:
    def __init__(self) -> None:
        self._outcomes: dict[str, ProfileOutcome] = defaultdict(ProfileOutcome)
        self._pattern_scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def record(self, query: str, profile: str, success: bool) -> None:
        key = profile
        self._outcomes[key].record(success)
        pattern = self._extract_pattern(query)
        if pattern:
            delta = 0.15 if success else -0.15
            self._pattern_scores[pattern][profile] = max(
                -0.5, min(1.0, self._pattern_scores[pattern].get(profile, 0.0) + delta)
            )
        logger.debug(
            "FeedbackLoop: profile={} success={} rate={:.2f}",
            profile, success, self._outcomes[key].success_rate,
        )

    def get_adjusted_confidence(self, profile: str, base_confidence: float, query: str = "") -> float:
        outcome = self._outcomes.get(profile)
        if outcome is None or (outcome.successes + outcome.failures) < 3:
            return base_confidence
        rate = outcome.success_rate
        adjustment = (rate - 0.5) * 0.3
        if query:
            pattern = self._extract_pattern(query)
            if pattern:
                pattern_adj = self._pattern_scores.get(pattern, {}).get(profile, 0.0)
                adjustment += pattern_adj * 0.1
        return max(0.1, min(1.0, base_confidence + adjustment))

    def suggest_alternative(self, failed_profile: str, query: str) -> str | None:
        pattern = self._extract_pattern(query)
        if not pattern:
            return None
        scores = self._pattern_scores.get(pattern, {})
        candidates = [(p, s) for p, s in scores.items() if p != failed_profile and s > 0.2]
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        return None

    def _extract_pattern(self, query: str) -> str:
        words = set(re.findall(r"\w{4,}", query.lower()))
        return "_".join(sorted(words)[:5])

    def status(self) -> dict[str, dict[str, Any]]:
        return {
            profile: {
                "successes": o.successes,
                "failures": o.failures,
                "success_rate": round(o.success_rate, 2),
            }
            for profile, o in self._outcomes.items()
        }


_feedback_loop = FeedbackLoop()


def get_feedback_loop() -> FeedbackLoop:
    return _feedback_loop


_KEYWORD_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"(?:security|vulnerability|cve|owasp|threat|exploit|injection|xss|ssrf|hardcoded|secret|token|permission|authenticat)"), "security", 0.85),
    (re.compile(r"(?:design|architect|architecture|structure|overview|diagram|system\s*design)"), "architect", 0.7),
    (re.compile(r"(?:plan|break\s*down|decompose|roadmap|milestone|task\s*list|steps? to|prioritize)"), "planner", 0.7),
    (re.compile(r"(?:debug|bug|error|crash|exception|stack.?trace|fix\s*this|not\s*working|broken|failing|traceback)"), "debugger", 0.85),
    (re.compile(r"(?:review|check\s*code|quality|lint|code\s*review|static\s*analysis)"), "reviewer", 0.75),
    (re.compile(r"(?:test|coverage|unit\s*test|integration\s*test|e2e\s*test|pytest|assert)"), "qa", 0.75),
    (re.compile(r"(?:implement|write\s*code|create\s*(?:a|an)\s+(?:function|class|module|file)|refactor|add\s+feature)"), "coder", 0.65),
    (re.compile(r"(?:write|create|generate|build|make|develop)"), "coder", 0.5),
    (re.compile(r"(?:research|investigate|explore|find|search|look\s*up|learn|study|analyze\s*codebase|discover|documentation)"), "researcher", 0.7),
]

_OVERRIDE_RULES: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"(?:hack|exploit|vuln|red\s*team|pentest|audit\s*security|owasp)"), "security", 0.95),
    (re.compile(r"(?:only\s*plan|just\s*plan|write\s*a\s*plan|create\s*a\s*plan)"), "planner", 0.9),
]


def _keyword_classify(text: str) -> ClassificationResult | None:
    lower = text.lower()
    best: tuple[str, float] | None = None
    for pattern, profile, score in _OVERRIDE_RULES:
        if pattern.search(lower) and (best is None or score > best[1]):
            best = (profile, score)
    for pattern, profile, score in _KEYWORD_RULES:
        if pattern.search(lower) and (best is None or score > best[1]):
            best = (profile, score)
    if best:
        return ClassificationResult(profile=best[0], confidence=best[1], raw_query=text)
    return None


class IntentRouter:
    def __init__(self, llm: Any, feedback: FeedbackLoop | None = None):
        self._llm = llm
        self._feedback = feedback or get_feedback_loop()

    async def classify(self, text: str, fallback_profile: str = "coder") -> ClassificationResult:
        keyword_result = _keyword_classify(text)
        if keyword_result is not None:
            keyword_result.confidence = self._feedback.get_adjusted_confidence(
                keyword_result.profile, keyword_result.confidence, text
            )
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
                if profile in ("architect", "planner", "coder", "reviewer", "debugger", "qa", "researcher", "security"):
                    confidence = self._feedback.get_adjusted_confidence(profile, confidence, text)
                    llm_result = ClassificationResult(profile=profile, confidence=confidence, raw_query=text)
                    if keyword_result:
                        if llm_result.confidence >= 0.6 and llm_result.profile != "coder":
                            return llm_result
                        if keyword_result.profile == llm_result.profile:
                            return llm_result
                        if llm_result.confidence >= 0.8:
                            return llm_result
                        return keyword_result
                    if llm_result.confidence >= 0.6:
                        return llm_result
        except Exception as e:
            logger.warning("IntentRouter: LLM classification failed: {}", e)

        if keyword_result:
            return keyword_result
        return ClassificationResult(profile=fallback_profile, confidence=0.5, raw_query=text)

    def record_outcome(self, query: str, profile: str, success: bool) -> None:
        self._feedback.record(query, profile, success)

    def suggest_after_failure(self, failed_profile: str, query: str) -> str | None:
        return self._feedback.suggest_alternative(failed_profile, query)

from __future__ import annotations

import re
from enum import StrEnum


class TaskType(StrEnum):
    CODING = "coding"
    AUTOMATION = "automation"
    HYBRID = "hybrid"
    QUERY = "query"


class ContextRouter:
    CODING_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"\b(write|create|implement|refactor|fix|debug|test|lint|type.?check|compile|function|class|method|file)\b", re.IGNORECASE),
        re.compile(r"(add|change|update|remove|delete)\s+(a\s+)?(function|class|method|file|test)", re.IGNORECASE),
        re.compile(r"pull.?(request|req)|pr\s|merge|commit|push|branch", re.IGNORECASE),
        re.compile(r"install|pip|npm|go\s+get|cargo|nuget", re.IGNORECASE),
        re.compile(r"read|edit|patch|diff|undo|redo", re.IGNORECASE),
        re.compile(r"performance|profiling|memory.?leak|optimize|bottleneck", re.IGNORECASE),
    ]

    AUTOMATION_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"\bschedule\b|cron|every\s+\d+\s+(hour|minute|day|week)", re.IGNORECASE),
        re.compile(r"send\s+(a\s+)?(message|notification|alert|email)", re.IGNORECASE),
        re.compile(r"monitor|watch|alert|notif(y|ication)|webhook|callback", re.IGNORECASE),
        re.compile(r"deploy|release|publish|rollback|ci/cd", re.IGNORECASE),
        re.compile(r"workflow|pipeline|dag|trigger|event.?driven", re.IGNORECASE),
        re.compile(r"backup|sync|migrate|import|export|transfer", re.IGNORECASE),
    ]

    HYBRID_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(write|create)\s+.*(and|then)\s+(run|execute|schedule|deploy)", re.IGNORECASE),
        re.compile(r"script\s+.*(cron|schedule|daemon|service)", re.IGNORECASE),
        re.compile(r"(test|build|compile)\s+.*(deploy|release|publish)", re.IGNORECASE),
        re.compile(r"(fix|patch|update)\s+.*(deploy|rollout)", re.IGNORECASE),
        re.compile(r"(write|create).+(monitor|watch|alert|notif)", re.IGNORECASE),
    ]

    _CONFIDENCE_THRESHOLD = 0.4
    _QUERY_CONFIDENCE = 0.3

    def classify(self, message: str) -> TaskType:
        coding_score = sum(1 for p in self.CODING_PATTERNS if p.search(message))
        automation_score = sum(1 for p in self.AUTOMATION_PATTERNS if p.search(message))
        hybrid_score = sum(1 for p in self.HYBRID_PATTERNS if p.search(message))

        if hybrid_score > 0:
            return TaskType.HYBRID
        if coding_score > 0 and automation_score == 0:
            return TaskType.CODING
        if automation_score > 0 and coding_score == 0:
            return TaskType.AUTOMATION
        if automation_score > coding_score:
            return TaskType.AUTOMATION
        if coding_score > automation_score:
            return TaskType.CODING
        if coding_score > 0:
            return TaskType.CODING
        return TaskType.QUERY

    def classify_with_confidence(self, message: str) -> tuple[TaskType, float]:
        coding_score = sum(1 for p in self.CODING_PATTERNS if p.search(message))
        automation_score = sum(1 for p in self.AUTOMATION_PATTERNS if p.search(message))
        hybrid_score = sum(1 for p in self.HYBRID_PATTERNS if p.search(message))
        total = coding_score + automation_score + hybrid_score or 1
        task_type = self.classify(message)

        confidence: float
        if task_type == TaskType.HYBRID:
            confidence = max(coding_score, automation_score, hybrid_score) / total
        elif task_type in (TaskType.CODING, TaskType.AUTOMATION):
            primary = coding_score if task_type == TaskType.CODING else automation_score
            confidence = primary / total
        else:
            confidence = self._QUERY_CONFIDENCE

        return task_type, min(confidence, 1.0)

    def get_system_prompt_modifier(self, message: str) -> str:
        task_type, confidence = self.classify_with_confidence(message)
        if confidence < self._CONFIDENCE_THRESHOLD:
            return ""

        modifiers: dict[TaskType, str] = {
            TaskType.CODING: (
                "Focus on code analysis and generation. Read existing files before making changes, "
                "run lint/typecheck after edits, and verify with tests."
            ),
            TaskType.AUTOMATION: (
                "Focus on task automation and orchestration. Use scheduling, webhooks, "
                "notifications, and channel integrations as needed."
            ),
            TaskType.HYBRID: (
                "This task requires both coding and automation. Write the code first, "
                "then set up scheduling, deployment, or integration as needed."
            ),
        }
        return modifiers.get(task_type, "")

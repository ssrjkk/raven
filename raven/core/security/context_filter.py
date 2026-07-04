from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from loguru import logger


class ContextVisibility(StrEnum):
    ALL = "all"
    ALLOWLIST = "allowlist"
    ALLOWLIST_QUOTE = "allowlist_quote"


_ROLE_MARKERS = re.compile(r"<\|(?:im_start|im_end|system|user|assistant|tool)(?:\|.*?)?\|>")
_SYS_PROMPT_PATTERNS = re.compile(
    r"(you\s+are\s+(?:a|an)?\s*(?:helpful|expert|ai|assistant)|"
    r"system\s*(?:prompt|instruction|message)|"
    r"ignore\s+(?:all\s+)?(?:previous|above)\s+instructions)",
    re.IGNORECASE,
)


@dataclass
class PIIDetection:
    entity_type: str
    start: int
    end: int
    text: str
    score: float = 1.0
    context: str = ""


@dataclass
class PIIPattern:
    name: str
    pattern: re.Pattern[str]
    replacement: str
    score: float = 1.0
    context_keywords: list[str] = field(default_factory=list)
    category: str = "generic"


_PII_CATEGORY_LABELS = {
    "credential": "[CREDENTIAL]",
    "personal": "[PERSONAL_INFO]",
    "financial": "[FINANCIAL]",
    "digital": "[DIGITAL_FOOTPRINT]",
    "location": "[LOCATION]",
}


class PIIEngine:
    def __init__(self):
        self._patterns = self._build_patterns()
        self._presidio_analyzer = None

    @staticmethod
    def _build_patterns() -> list[PIIPattern]:
        return [
            # ── Credentials & Keys ──
            PIIPattern(
                "ssh_key",
                re.compile(
                    r"-----BEGIN\s*(?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE\s*KEY.*?-----END\s*(?:RSA|DSA|EC|OPENSSH|PGP)?\s*PRIVATE\s*KEY-----",
                    re.DOTALL,
                ),
                "[SSH_KEY]",
                score=1.0,
                category="credential",
            ),
            PIIPattern(
                "aws_key",
                re.compile(
                    r"(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}",
                ),
                "[AWS_KEY]",
                score=0.95,
                context_keywords=["aws", "amazon", "s3", "ec2"],
                category="credential",
            ),
            PIIPattern(
                "github_token",
                re.compile(
                    r"(?:ghp_|gho_|ghu_|ghs_|ghr_)[a-zA-Z0-9]{36}",
                ),
                "[GITHUB_TOKEN]",
                score=0.95,
                context_keywords=["github", "git"],
                category="credential",
            ),
            PIIPattern(
                "slack_token",
                re.compile(
                    r"x(?:ox[abp]|app|opsb|orb)[-0-9a-zA-Z]{24,72}",
                ),
                "[SLACK_TOKEN]",
                score=0.95,
                context_keywords=["slack"],
                category="credential",
            ),
            PIIPattern(
                "telegram_token",
                re.compile(
                    r"\b\d{8,10}:[a-zA-Z0-9_-]{35}\b",
                ),
                "[TELEGRAM_TOKEN]",
                score=0.95,
                context_keywords=["telegram", "bot"],
                category="credential",
            ),
            PIIPattern(
                "discord_token",
                re.compile(
                    r"[a-zA-Z0-9_-]{24}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27}",
                ),
                "[DISCORD_TOKEN]",
                score=0.9,
                context_keywords=["discord"],
                category="credential",
            ),
            PIIPattern(
                "jwt",
                re.compile(
                    r"eyJ[a-zA-Z0-9_-]{4,}\.[a-zA-Z0-9_-]{4,}\.[a-zA-Z0-9_-]{2,}",
                ),
                "[JWT]",
                score=0.9,
                context_keywords=["jwt", "token", "bearer"],
                category="credential",
            ),
            PIIPattern(
                "api_key_generic",
                re.compile(
                    r"(?:(?:sk|pk|api|key|secret|token)[-_])[a-zA-Z0-9]{16,64}",
                ),
                "[API_KEY]",
                score=0.7,
                context_keywords=["key", "secret", "token", "api", "password", "auth"],
                category="credential",
            ),
            PIIPattern(
                "connection_string",
                re.compile(
                    r"\b(?:postgres|mysql|mongodb|redis|amqp|rabbitmq)://[^\s<>\"']+",
                ),
                "[CONNECTION_STRING]",
                score=0.95,
                category="credential",
            ),
            PIIPattern(
                "basic_auth_url",
                re.compile(
                    r"\bhttps?://[^\s:<>\"']+:[^\s@<>\"']+@[^\s<>\"']+",
                ),
                "[URL_WITH_CREDENTIALS]",
                score=0.95,
                category="credential",
            ),
            PIIPattern(
                "password_in_text",
                re.compile(
                    r"(?i)(?:password|passwd|pwd|secret)\s*[:=]\s*['\"]?[^\s,;\"']+['\"]?",
                ),
                "[PASSWORD]",
                score=0.85,
                category="credential",
            ),
            # ── Personal Information ──
            PIIPattern(
                "email",
                re.compile(
                    r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
                    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}",
                ),
                "[EMAIL]",
                score=0.95,
                category="personal",
            ),
            PIIPattern(
                "phone_international",
                re.compile(
                    r"\+\d{1,3}[-\s.]?\(?\d{1,4}\)?[-\s.]?\d{1,4}[-\s.]?\d{1,9}",
                ),
                "[PHONE]",
                score=0.9,
                context_keywords=["phone", "call", "tel", "mobile", "cell", "whatsapp"],
                category="personal",
            ),
            PIIPattern(
                "phone_us",
                re.compile(
                    r"\(?\d{3}\)?[-\s.]?\d{3}[-\s.]?\d{4}",
                ),
                "[PHONE]",
                score=0.7,
                category="personal",
            ),
            PIIPattern(
                "ssn",
                re.compile(
                    r"\b\d{3}-\d{2}-\d{4}\b",
                ),
                "[SSN]",
                score=0.95,
                context_keywords=["ssn", "social", "security"],
                category="personal",
            ),
            PIIPattern(
                "passport_us",
                re.compile(
                    r"\b\d{9}\b",
                ),
                "[PASSPORT]",
                score=0.4,
                context_keywords=["passport", "travel", "visa"],
                category="personal",
            ),
            PIIPattern(
                "drivers_license",
                re.compile(
                    r"\b[A-Z]\d{3,8}\b",
                ),
                "[DL]",
                score=0.3,
                context_keywords=["license", "dl", "driver", "licence"],
                category="personal",
            ),
            PIIPattern(
                "dob",
                re.compile(
                    r"\b\d{1,2}[/-]\d{1,2}[/-](?:\d{4}|\d{2})\b",
                ),
                "[DOB]",
                score=0.5,
                context_keywords=["dob", "birth", "born", "birthday", "date of birth"],
                category="personal",
            ),
            # ── Financial ──
            PIIPattern(
                "credit_card_visa_mc",
                re.compile(
                    r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
                ),
                "[CREDIT_CARD]",
                score=0.95,
                context_keywords=["card", "credit", "debit", "payment", "visa", "mastercard", "amex"],
                category="financial",
            ),
            PIIPattern(
                "credit_card_amex",
                re.compile(
                    r"\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b",
                ),
                "[CREDIT_CARD]",
                score=0.95,
                category="financial",
            ),
            PIIPattern(
                "iban",
                re.compile(
                    r"\b[A-Z]{2}\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{0,4}\b",
                ),
                "[IBAN]",
                score=0.85,
                context_keywords=["iban", "bank", "account"],
                category="financial",
            ),
            PIIPattern(
                "routing_number",
                re.compile(
                    r"\b\d{9}\b",
                ),
                "[ROUTING_NUMBER]",
                score=0.3,
                context_keywords=["routing", "aba", "ach", "bank"],
                category="financial",
            ),
            # ── Digital Footprints ──
            PIIPattern(
                "ipv4",
                re.compile(
                    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
                ),
                "[IP_ADDRESS]",
                score=0.8,
                category="digital",
            ),
            PIIPattern(
                "ipv6",
                re.compile(
                    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
                ),
                "[IP_ADDRESS]",
                score=0.85,
                category="digital",
            ),
            PIIPattern(
                "mac_address",
                re.compile(
                    r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b",
                ),
                "[MAC_ADDRESS]",
                score=0.85,
                category="digital",
            ),
            PIIPattern(
                "bitcoin",
                re.compile(
                    r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b",
                ),
                "[BITCOIN_ADDRESS]",
                score=0.9,
                category="financial",
            ),
            PIIPattern(
                "ethereum",
                re.compile(
                    r"\b0x[a-fA-F0-9]{40}\b",
                ),
                "[ETHEREUM_ADDRESS]",
                score=0.9,
                category="financial",
            ),
            PIIPattern(
                "hex_token",
                re.compile(
                    r"\b[a-fA-F0-9]{32,64}\b",
                ),
                "[TOKEN]",
                score=0.3,
                context_keywords=["token", "hash", "hex", "session", "csrf", "nonce"],
                category="digital",
            ),
            PIIPattern(
                "session_cookie",
                re.compile(
                    r"(?i)(?:session|sid|token|auth)\s*[:=]\s*['\"]?[a-zA-Z0-9+/]{16,128}={0,2}['\"]?",
                ),
                "[SESSION_TOKEN]",
                score=0.75,
                category="digital",
            ),
        ]

    def _try_init_presidio(self):
        if self._presidio_analyzer is not None:
            return
        try:
            from presidio_analyzer import AnalyzerEngine

            self._presidio_analyzer = AnalyzerEngine()
        except ImportError:
            logger.debug("[context_filter] presidio_analyzer not available — using regex patterns only")

    def analyze(self, text: str, pii_types: list[str] | None = None) -> list[PIIDetection]:
        finds: list[PIIDetection] = []
        seen_spans: set[tuple[int, int]] = set()

        for pat in self._patterns:
            if pii_types is not None and pat.name not in pii_types and pat.category not in pii_types:
                continue
            for m in pat.pattern.finditer(text):
                start, end = m.start(), m.end()
                overlapped = any(s < end and e > start for s, e in seen_spans)
                if overlapped:
                    continue
                score = pat.score
                context_window = text[max(0, start - 40) : min(len(text), end + 40)].lower()
                if pat.context_keywords and any(kw in context_window for kw in pat.context_keywords):
                    score = min(1.0, score + 0.15)
                seen_spans.add((start, end))
                finds.append(
                    PIIDetection(
                        entity_type=pat.name,
                        start=start,
                        end=end,
                        text=m.group(),
                        score=round(score, 2),
                        context=text[max(0, start - 20) : min(len(text), end + 20)],
                    )
                )

        if pii_types is None or "presidio" in pii_types:
            try:
                self._try_init_presidio()
                if self._presidio_analyzer:
                    presidio_results = self._presidio_analyzer.analyze(text=text, language="en")
                    for r in presidio_results:
                        start, end = r.start, r.end
                        overlapped = any(s < end and e > start for s, e in seen_spans)
                        if overlapped:
                            continue
                        seen_spans.add((start, end))
                        finds.append(
                            PIIDetection(
                                entity_type=f"presidio_{r.entity_type}",
                                start=start,
                                end=end,
                                text=text[start:end],
                                score=round(r.score, 2),
                            )
                        )
            except Exception as exc:
                logger.debug("Presidio analysis failed: {}", exc)

        finds.sort(key=lambda f: f.start)
        return finds

    def redact(self, text: str, pii_types: list[str] | None = None, operators: dict[str, str] | None = None) -> str:
        finds = self.analyze(text, pii_types=pii_types)
        if not finds:
            return text

        if operators and "mask" in operators:
            return self._apply_mask(text, finds, operators["mask"])

        replacements = {p.name: p.replacement for p in self._patterns}
        result_parts: list[str] = []
        last_end = 0
        for f in finds:
            label = replacements.get(f.entity_type) or _PII_CATEGORY_LABELS.get(
                self._category_for(f.entity_type), f"[{f.entity_type.upper()}]"
            )
            if operators and f.entity_type in operators:
                label = operators[f.entity_type]
            result_parts.append(text[last_end : f.start])
            result_parts.append(label)
            last_end = f.end
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    def mask(self, text: str, pii_types: list[str] | None = None, char: str = "*") -> str:
        finds = self.analyze(text, pii_types=pii_types)
        if not finds:
            return text
        return self._apply_mask(text, finds, char)

    @staticmethod
    def _apply_mask(text: str, finds: list[PIIDetection], char: str) -> str:
        result_parts: list[str] = []
        last_end = 0
        for f in finds:
            result_parts.append(text[last_end : f.start])
            masked = char * (f.end - f.start)
            if len(masked) > 4:
                masked = text[f.start : f.start + 1] + masked[1:-1] + text[f.end - 1 : f.end]
                if char != "*":
                    masked = char * (f.end - f.start)
            result_parts.append(masked)
            last_end = f.end
        result_parts.append(text[last_end:])
        return "".join(result_parts)

    @staticmethod
    def _category_for(entity_type: str) -> str:
        for pat in _ENGINE._patterns:
            if pat.name == entity_type:
                return pat.category
        return "generic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "patterns": len(self._patterns),
            "presidio_available": self._presidio_analyzer is not None,
        }


_ENGINE = PIIEngine()


def redact_pii(text: str, pii_types: list[str] | None = None) -> str:
    return _ENGINE.redact(text, pii_types=pii_types)


def mask_pii(text: str, pii_types: list[str] | None = None, char: str = "*") -> str:
    return _ENGINE.mask(text, pii_types=pii_types, char=char)


def analyze_pii(text: str, pii_types: list[str] | None = None) -> list[PIIDetection]:
    return _ENGINE.analyze(text, pii_types=pii_types)


def sanitize_external_content(text: str, source: str = "unknown", channel: str = "", sender: str = "") -> str:
    cleaned = _ROLE_MARKERS.sub("", text)
    cleaned = _SYS_PROMPT_PATTERNS.sub("[REDACTED]", cleaned)
    cleaned = redact_pii(cleaned)
    wrapped = (
        f"<<<EXTERNAL_UNTRUSTED_CONTENT>>>\n"
        f"Source: {source}\n"
        f"Channel: {channel}\n"
        f"Sender: {sender}\n"
        f"---\n"
        f"{cleaned}\n"
        f"<<<END_EXTERNAL_CONTENT>>>"
    )
    return wrapped


def filter_context_by_visibility(
    context: str,
    visibility: ContextVisibility,
    user_is_allowlisted: bool,
    user_id: str = "",
) -> str:
    if visibility == ContextVisibility.ALL:
        return context
    if visibility == ContextVisibility.ALLOWLIST:
        if not user_is_allowlisted:
            return "[Context filtered: only allowlisted users can view context]"
        return context
    if visibility == ContextVisibility.ALLOWLIST_QUOTE:
        if not user_is_allowlisted:
            return "[Context filtered: only allowlisted users can view context. Use quoting to share specific context.]"
        return context
    return context


__all__ = [
    "ContextVisibility",
    "PIIDetection",
    "PIIEngine",
    "redact_pii",
    "mask_pii",
    "analyze_pii",
    "sanitize_external_content",
    "filter_context_by_visibility",
]

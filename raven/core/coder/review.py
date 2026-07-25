from __future__ import annotations

from typing import Any

from raven.core.coder.models import ReviewComment, ReviewSeverity


class CodeReviewer:
    def __init__(self):
        self._checks: list[Any] = []

    async def review_diff(self, diff_text: str, language: str = "") -> list[ReviewComment]:
        comments: list[ReviewComment] = []

        comments.extend(self._check_syntax_errors(diff_text))
        comments.extend(self._check_security_issues(diff_text))
        comments.extend(self._check_style_issues(diff_text, language))

        return comments

    async def review_file(self, file_path: str, content: str, language: str = "") -> list[ReviewComment]:
        comments: list[ReviewComment] = []
        comments.extend(self._check_long_lines(content, file_path))
        comments.extend(self._check_security_issues(content, file_path))
        comments.extend(self._check_todo_comments(content, file_path))
        comments.extend(self._check_import_wildcard(content, file_path))
        comments.extend(self._check_syntax_errors(content, file_path))
        if language == "python":
            comments.extend(self._check_python_specific(content, file_path))
        return comments

    def _check_syntax_errors(self, diff: str, file_path: str = "diff") -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(diff.splitlines(), 1):
            if line.startswith("+") and len(line) > 200:
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.WARNING,
                        message=f"Line {i} is too long ({len(line)} chars). Consider breaking it up.",
                        suggestion="Split long lines into multiple shorter ones for readability.",
                    )
                )
        return comments

    def _check_security_issues(self, diff: str, file_path: str = "diff") -> list[ReviewComment]:
        comments = []
        patterns = [
            ("password", "Hardcoded password detected", "Use environment variables or secrets manager"),
            ("api_key", "Hardcoded API key", "Use environment variables or secrets manager"),
            ("secret", "Hardcoded secret detected", "Use environment variables or secrets manager"),
            ("token", "Hardcoded token detected", "Use environment variables or secrets manager"),
            ("eval(", "Use of eval() is dangerous", "Avoid eval() — use safer alternatives"),
            ("exec(", "Use of exec() is dangerous", "Avoid exec() — use safer alternatives"),
        ]
        for i, line in enumerate(diff.splitlines(), 1):
            lower = line.lower()
            for pattern, msg, suggestion in patterns:
                if pattern in lower and not lower.strip().startswith(("#", "//", "--", "/*")):
                    comments.append(
                        ReviewComment(
                            file=file_path,
                            line=i,
                            severity=ReviewSeverity.CRITICAL
                            if "password" in pattern or "secret" in pattern or "api_key" in pattern
                            else ReviewSeverity.WARNING,
                            message=msg,
                            suggestion=suggestion,
                        )
                    )
        return comments

    def _check_style_issues(self, diff: str, language: str, file_path: str = "diff") -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(diff.splitlines(), 1):
            stripped = line.strip()
            if stripped.endswith((" ", "\t")):
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.SUGGESTION,
                        message="Trailing whitespace detected",
                        suggestion="Remove trailing whitespace.",
                    )
                )
        return comments

    def _check_long_lines(self, content: str, file_path: str) -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(content.splitlines(), 1):
            if len(line) > 120:
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.SUGGESTION,
                        message=f"Line too long ({len(line)} > 120 chars)",
                        suggestion="Break into multiple lines for better readability.",
                    )
                )
        return comments

    def _check_todo_comments(self, content: str, file_path: str) -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(content.splitlines(), 1):
            if "TODO" in line or "FIXME" in line or "HACK" in line or "XXX" in line:
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.SUGGESTION,
                        message=f"Unresolved comment: {line.strip()[:60]}",
                        suggestion="Address or track this item before merging.",
                    )
                )
        return comments

    def _check_import_wildcard(self, content: str, file_path: str) -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(content.splitlines(), 1):
            if "import *" in line or ("from " in line and " import *" in line):
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.WARNING,
                        message="Wildcard import detected",
                        suggestion="Import specific names instead of using * to avoid namespace pollution.",
                    )
                )
        return comments

    def _check_python_specific(self, content: str, file_path: str) -> list[ReviewComment]:
        comments = []
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if "except:" in stripped and not stripped.startswith("#"):
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.WARNING,
                        message="Bare except clause",
                        suggestion="Catch specific exceptions instead of using bare except.",
                    )
                )
            if "== None" in stripped or "!= None" in stripped:
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.SUGGESTION,
                        message="Comparison to None using == / !=",
                        suggestion="Use 'is None' / 'is not None' instead.",
                    )
                )
            if stripped.startswith("print(") and not stripped.startswith("#"):
                comments.append(
                    ReviewComment(
                        file=file_path,
                        line=i,
                        severity=ReviewSeverity.SUGGESTION,
                        message="Use of print() in production code",
                        suggestion="Consider using a logger instead of print().",
                    )
                )
        return comments

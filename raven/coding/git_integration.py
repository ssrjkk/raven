from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from raven.core.llm import LLMProvider
    _LLM_AVAILABLE = True
except ImportError:
    _LLM_AVAILABLE = False
    LLMProvider = None  # type: ignore[assignment,misc]


@dataclass
class FileChange:
    path: str
    old_content: str = ""
    new_content: str = ""
    change_type: str = "edit"


@dataclass
class CommitResult:
    success: bool
    message: str
    commit_hash: str = ""
    error: str = ""


@dataclass
class PRResult:
    success: bool
    url: str = ""
    error: str = ""


@dataclass
class ReviewComment:
    file: str
    line: int
    severity: str
    message: str


@dataclass
class ReviewResult:
    comments: list[ReviewComment] = field(default_factory=list)
    summary: str = ""


_LONG_LINE_THRESHOLD = 200
_GIT_TIMEOUT = 60


class GitIntegration:
    def __init__(self, repo_path: str | Path | None = None, llm_provider: LLMProvider | None = None) -> None:
        self._repo = Path(repo_path).resolve() if repo_path else Path.cwd()
        self._llm = llm_provider

    def _run(self, *args: str) -> tuple[str, str]:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(self._repo), *args],  # noqa: S607
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
        return result.stdout.strip(), result.stderr.strip()

    def _parse_diff_files(self, diff: str) -> set[str]:
        files: set[str] = set()
        for line in diff.split("\n"):
            if line.startswith("diff --git a/"):
                parts = line.split(" b/", 1)
                if len(parts) > 1:
                    files.add(parts[1])
        return files

    def _count_changes(self, diff: str) -> tuple[int, int]:
        lines = [line for line in diff.split("\n") if line.startswith(("+", "-")) and not line.startswith(("---", "+++"))]
        additions = sum(1 for line in lines if line.startswith("+"))
        removals = sum(1 for line in lines if line.startswith("-"))
        return additions, removals

    def is_repo(self) -> bool:
        stdout, _ = self._run("rev-parse", "--git-dir")
        return bool(stdout)

    def get_branch(self) -> str:
        stdout, _ = self._run("rev-parse", "--abbrev-ref", "HEAD")
        return stdout or "unknown"

    def is_branch(self) -> bool:
        return self.get_branch() not in ("HEAD", "main", "master")

    def get_diff(self, staged: bool = False) -> str:
        stdout, _ = self._run("diff", "--cached") if staged else self._run("diff")
        return stdout

    def get_log(self, count: int = 10) -> list[dict[str, str]]:
        stdout, _ = self._run("log", f"--max-count={count}", "--format=%h|%s|%an|%ad", "--date=short")
        entries: list[dict[str, str]] = []
        for line in stdout.split("\n"):
            parts = line.split("|", 3)
            if len(parts) == 4:
                entries.append({"hash": parts[0], "message": parts[1], "author": parts[2], "date": parts[3]})
        return entries

    def stage_all(self) -> str:
        _, stderr = self._run("add", "-A")
        return stderr

    def commit(self, message: str) -> CommitResult:
        stdout, stderr = self._run("commit", "-m", message)
        if stderr and "nothing to commit" in stderr:
            return CommitResult(success=False, message="Nothing to commit", error=stderr)
        if "changed" not in stdout and "created" not in stdout:
            return CommitResult(success=False, message=stdout or stderr, error=stderr)
        hash_stdout, _ = self._run("rev-parse", "--short", "HEAD")
        return CommitResult(success=True, message=stdout, commit_hash=hash_stdout)

    def auto_commit(self, additional_context: str = "") -> CommitResult:
        if not self.is_repo():
            return CommitResult(success=False, message="Not a git repository")

        diff = self.get_diff()
        if not diff:
            self.stage_all()
            diff = self.get_diff(staged=True)
            if not diff:
                return CommitResult(success=False, message="No changes to commit")
        else:
            self.stage_all()
            diff = self.get_diff(staged=True)

        commit_msg = self._generate_commit_message(diff, additional_context)
        return self.commit(commit_msg)

    def _generate_commit_message(self, diff: str, context: str = "") -> str:
        additions, removals = self._count_changes(diff)

        if additions > 0 and removals == 0:
            prefix = "feat"
        elif removals > 0 and additions == 0:
            prefix = "fix"
        elif "test" in diff.lower():
            prefix = "test"
        elif "doc" in diff.lower() or "readme" in diff.lower():
            prefix = "docs"
        elif "refactor" in diff.lower():
            prefix = "refactor"
        else:
            prefix = "chore"

        changed_files = sorted(self._parse_diff_files(diff))
        scope = f"({Path(changed_files[0]).stem})" if changed_files else ""

        files_str = ", ".join(changed_files[:5])
        if len(changed_files) > 5:
            files_str += f" +{len(changed_files) - 5} more"

        msg = f"{prefix}{scope}: {files_str}"
        if context:
            msg += f"\n\n{context}"
        msg += f"\n\n(additions: {additions}, removals: {removals})"
        return msg

    def create_pr(self, title: str = "", body: str = "") -> PRResult:
        if not self.is_repo():
            return PRResult(success=False, error="Not a git repository")
        if not self.is_branch():
            return PRResult(success=False, error="Not on a feature branch")

        branch = self.get_branch()
        if not title:
            title = f"PR: {branch}"

        diff = self.get_diff(staged=True)
        if not diff:
            self.stage_all()
            diff = self.get_diff(staged=True)

        if not body:
            body = self._generate_pr_description(diff)

        _, stderr = self._run("push", "--set-upstream", "origin", branch)
        if stderr and "error" in stderr.lower():
            return PRResult(success=False, error=stderr)

        try:
            pr_stdout, _ = self._run("-c", "core.pager=", "push", "origin", branch)
            for line in pr_stdout.split("\n"):
                if "pull/new" in line or "/pull/" in line:
                    return PRResult(success=True, url=line.strip())
        except Exception as exc:
            logger.debug("git push PR detection failed: {}", exc)

        return PRResult(success=True, url=f"(pushed branch {branch})")

    def _generate_pr_description(self, diff: str) -> str:
        changed_files = sorted(self._parse_diff_files(diff))
        additions, removals = self._count_changes(diff)

        desc = f"## Summary\n\nChanges in {len(changed_files)} file(s):\n\n"
        for f in changed_files:
            desc += f"- `{f}`\n"
        desc += f"\n## Stats\n\n- **Additions:** {additions}\n- **Removals:** {removals}\n"
        return desc

    def review(self, file_path: str | None = None) -> ReviewResult:
        diff = self.get_diff() if file_path is None else self._get_file_diff(file_path)
        if not diff:
            return ReviewResult()

        comments: list[ReviewComment] = []
        issues_found: list[str] = []

        for line in diff.split("\n"):
            if not line.startswith("+") or line.startswith(("+++", "---")):
                continue

            stripped = line[1:].strip()
            if len(stripped) > _LONG_LINE_THRESHOLD:
                comments.append(ReviewComment(
                    file=file_path or "(unknown)", line=0,
                    severity="warning",
                    message=f"Line too long ({len(stripped)} chars, max {_LONG_LINE_THRESHOLD})",
                ))
                issues_found.append("long_line")

            if stripped.endswith(("}", ")", ";", ":", ",")):
                pass
            elif "print(" in stripped:
                comments.append(ReviewComment(
                    file=file_path or "(unknown)", line=0,
                    severity="info",
                    message="Consider using logger instead of print()",
                ))
                issues_found.append("print")

            if "TODO" in stripped or "FIXME" in stripped:
                comments.append(ReviewComment(
                    file=file_path or "(unknown)", line=0,
                    severity="info",
                    message=f"Unresolved marker: {stripped}",
                ))
                issues_found.append("marker")

            if ("except:" in stripped or "except Exception:" in stripped) and "pass" in stripped:
                comments.append(ReviewComment(
                    file=file_path or "(unknown)", line=0,
                    severity="warning",
                    message="Bare except with pass — silent error swallowing",
                ))
                issues_found.append("silent_except")

        summary = f"Found {len(comments)} issue(s)"
        if issues_found:
            summary += f": {', '.join(set(issues_found))}"
        return ReviewResult(comments=comments, summary=summary)

    def _get_file_diff(self, file_path: str) -> str:
        stdout, _ = self._run("diff", file_path)
        return stdout

    def resolve_conflict(self, file_path: str) -> str:
        content = Path(self._repo / file_path).read_text(encoding="utf-8")
        if "<<<<<<<" not in content:
            return content

        resolved: list[str] = []
        skip = False
        for line in content.split("\n"):
            if line.startswith("<<<<<<<") or line.startswith("======="):
                skip = True
            elif line.startswith(">>>>>>>"):
                skip = False
            elif not skip:
                resolved.append(line)

        return "\n".join(resolved)

    def status(self) -> dict[str, Any]:
        if not self.is_repo():
            return {"is_repo": False}
        stdout, _ = self._run("status", "--porcelain")
        changes = [line.strip() for line in stdout.split("\n") if line.strip()]
        return {
            "is_repo": True,
            "branch": self.get_branch(),
            "is_branch": self.is_branch(),
            "changed_files": len(changes),
            "changes": changes[:20],
        }

    # ---- LLM-powered async methods -------------------------------------------

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if not _LLM_AVAILABLE or self._llm is None:
            return ""
        try:
            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})
            resp = await self._llm.complete(messages, model="")
            return resp.content.strip()
        except Exception as exc:
            logger.warning("GitIntegration LLM call failed: {}", exc)
            return ""

    async def _generate_llm_commit_message(self, diff: str, context: str = "") -> str:
        user_prompt = f"Generate a conventional commit message for this diff:\n\n{diff[:4000]}"
        if context:
            user_prompt += f"\n\nAdditional context: {context}"
        result = await self._call_llm(
            system_prompt="You are a git commit message generator. "
                          "Respond with only the commit message (single line subject + optional body).",
            user_prompt=user_prompt,
        )
        return result or self._generate_commit_message(diff, context)

    async def _generate_llm_pr_description(self, diff: str) -> str:
        result = await self._call_llm(
            system_prompt="You are a PR description generator. "
                          "Provide a markdown summary with sections for changes, rationale, and risks.",
            user_prompt=f"Generate a detailed PR description for this diff:\n\n{diff[:4000]}",
        )
        return result or self._generate_pr_description(diff)

    async def auto_commit_async(self, additional_context: str = "") -> CommitResult:
        if not self.is_repo():
            return CommitResult(success=False, message="Not a git repository")

        diff = self.get_diff()
        if not diff:
            self.stage_all()
            diff = self.get_diff(staged=True)
            if not diff:
                return CommitResult(success=False, message="No changes to commit")
        else:
            self.stage_all()
            diff = self.get_diff(staged=True)

        commit_msg = await self._generate_llm_commit_message(diff, additional_context)
        return self.commit(commit_msg)

    async def create_pr_async(self, title: str = "", body: str = "") -> PRResult:
        if not self.is_repo():
            return PRResult(success=False, error="Not a git repository")
        if not self.is_branch():
            return PRResult(success=False, error="Not on a feature branch")

        branch = self.get_branch()
        if not title:
            title = f"PR: {branch}"

        diff = self.get_diff(staged=True)
        if not diff:
            self.stage_all()
            diff = self.get_diff(staged=True)

        if not body:
            body = await self._generate_llm_pr_description(diff)

        _, stderr = self._run("push", "--set-upstream", "origin", branch)
        if stderr and "error" in stderr.lower():
            return PRResult(success=False, error=stderr)

        try:
            pr_stdout, _ = self._run("-c", "core.pager=", "push", "origin", branch)
            for line in pr_stdout.split("\n"):
                if "pull/new" in line or "/pull/" in line:
                    return PRResult(success=True, url=line.strip())
        except Exception as exc:
            logger.debug("git push PR detection failed: {}", exc)

        return PRResult(success=True, url=f"(pushed branch {branch})")

    async def llm_review(self, file_path: str | None = None) -> ReviewResult:
        diff = self.get_diff() if file_path is None else self._get_file_diff(file_path)
        if not diff:
            return ReviewResult(comments=[], summary="No diff to review")

        prompt = (
            "Review the following git diff and provide structured feedback.\n"
            "Respond with a JSON object with exactly these keys:\n"
            '  - "summary": a 1-2 sentence overall assessment\n'
            '  - "comments": a list of objects, each with:\n'
            '      - "file": the file path\n'
            '      - "line": the line number (0 if unknown)\n'
            '      - "severity": "info", "warning", or "error"\n'
            '      - "message": the review comment text\n'
            f"\nDiff:\n```\n{diff[:6000]}\n```\n"
        )
        response = await self._call_llm(
            system_prompt="You are a senior code reviewer. Analyze code changes and provide constructive feedback. Respond with valid JSON only.",
            user_prompt=prompt,
        )
        if not response:
            return self.review(file_path)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            try:
                start = response.index("{")
                end = response.rindex("}") + 1
                data = json.loads(response[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("Failed to parse LLM review JSON, falling back to rule-based review")
                return self.review(file_path)

        comments_data = data.get("comments", []) if isinstance(data, dict) else []
        comments = [
            ReviewComment(
                file=c.get("file", file_path or "(unknown)"),
                line=c.get("line", 0),
                severity=c.get("severity", "info"),
                message=c.get("message", ""),
            )
            for c in comments_data
        ]
        summary = data.get("summary", f"LLM review found {len(comments)} issue(s)") if isinstance(data, dict) else ""
        return ReviewResult(comments=comments, summary=summary)

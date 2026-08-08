from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    instructions: str
    paths: list[Path] = field(default_factory=list)


_BUILTIN_SKILLS: dict[str, Skill] = {}


def _register_builtin(id: str, name: str, description: str, instructions: str) -> None:
    _BUILTIN_SKILLS[id] = Skill(name=name, description=description, instructions=instructions)


_register_builtin(
    "security-audit",
    "Security Audit",
    "Review code for common security vulnerabilities (injection, XSS, SSRF, secrets exposure).",
    (
        "You are running a security audit. Follow these rules:\n"
        "1. Read all modified/new files first\n"
        "2. Check for: path injection, command injection, XSS, SSRF, hardcoded secrets, SQL injection\n"
        "3. For each finding, report: file, line, severity (low/med/high/critical), and a fix suggestion\n"
        "4. Never modify files during audit only report findings\n"
        "5. Output a final summary table with severity counts"
    ),
)

_register_builtin(
    "code-review",
    "Code Review",
    "Review a pull request or set of changes for correctness, style, and maintainability.",
    (
        "You are reviewing code changes. Follow these rules:\n"
        "1. Read the diff or the relevant files\n"
        "2. Check for: logic errors, missing edge cases, type mismatches, dead code, style issues\n"
        "3. For each issue, reference the exact file and line number\n"
        "4. Separate your feedback into Required fixes Suggestions and Praise\n"
        "5. Provide a summary rating LGTM / Minor Issues / Needs Changes"
    ),
)

_register_builtin(
    "refactor",
    "Refactoring",
    "Refactor code to improve structure, reduce duplication, or modernize patterns.",
    (
        "You are refactoring code. Follow these rules:\n"
        "1. First understand the full codebase structure read relevant files\n"
        "2. Plan the refactoring steps before executing\n"
        "3. Make one change at a time and verify with tests/lint after each step\n"
        "4. Keep the public API unchanged unless explicitly requested\n"
        "5. Update imports and references across the codebase\n"
        "6. After refactoring run lint and tests to confirm nothing is broken"
    ),
)

_register_builtin(
    "test-writer",
    "Test Writer",
    "Write comprehensive tests for code. Prefer real tests over mocks.",
    (
        "You are writing tests. Follow these rules:\n"
        "1. Read the source files to understand the API and edge cases\n"
        "2. Check existing test files for style conventions and patterns\n"
        "3. Cover happy path error cases edge cases empty input None boundaries\n"
        "4. Use real assertions assert x == y never print-based testing\n"
        "5. Run tests after writing to confirm they pass\n"
        "6. If tests use async verify the test runner supports it"
    ),
)

_register_builtin(
    "debug",
    "Debugging",
    "Diagnose and fix test failures, runtime errors, or unexpected behavior.",
    (
        "You are debugging an issue. Follow these rules:\n"
        "1. Reproduce the error first run the failing command/test\n"
        "2. Read the full error traceback and identify the root cause\n"
        "3. Check recent changes git diff git log for the likely culprit\n"
        "4. Formulate a hypothesis before making changes\n"
        "5. Apply the fix and re-run to confirm resolution\n"
        "6. If stuck after 3 attempts delegate to a sub-task with full context"
    ),
)

_register_builtin(
    "remote-registry",
    "Skill Registry",
    "Download skills from a remote skill registry (like ClawHub).",
    (
        "You can download skills from a remote registry using the skill tool. "
        "Set the registry URL first with set_skill_registry, then use download_skill to fetch skills."
    ),
)

_register_builtin(
    "dependency-update",
    "Dependency Update",
    "Update project dependencies safely check for updates apply and verify compatibility.",
    (
        "You are updating dependencies. Follow these rules:\n"
        "1. Check current dependency files requirements.txt pyproject.toml Cargo.toml package.json\n"
        "2. Research latest compatible versions use web_search if needed\n"
        "3. Update one dependency at a time\n"
        "4. After each update run install lint typecheck tests\n"
        "5. If a breaking change is found research migration steps\n"
        "6. Commit changes with a descriptive message per dependency"
    ),
)


def _manager(cwd: Path | None = None) -> Any:
    from raven.core.artifacts.manager import ArtifactManager

    return ArtifactManager(cwd=cwd, import_agents_md=False)


def _to_skill(index: Any) -> Skill:
    from raven.core.artifacts import loader as artifact_loader

    loaded = artifact_loader.load_skill(index)
    text = loaded.instructions
    if loaded.examples:
        text = f"{text}\n\nExamples:\n" + "\n\n".join(loaded.examples)
    return Skill(
        name=loaded.name,
        description=loaded.description,
        instructions=text,
        paths=list(loaded.paths),
    )


def discover_skills(cwd: Path | None = None) -> dict[str, Skill]:
    result = dict(_BUILTIN_SKILLS)
    for skill in _manager(cwd).skills_index():
        result.setdefault(skill.name.lower(), _to_skill(skill))
    return result


def load_skill(skill_id: str, cwd: Path | None = None) -> str:
    manager = _manager(cwd)
    index = manager.skill_index(skill_id) or manager.skill_index(skill_id.lower())
    if index is None:
        available = ", ".join(sorted(discover_skills(cwd)))
        return f"Skill '{skill_id}' not found. Available: {available or '(none)'}"
    skill = _to_skill(index)
    return f"# Skill: {skill.name}\n\n{skill.description}\n\n## Instructions\n\n{skill.instructions}"


def list_skills(cwd: Path | None = None) -> list[str]:
    return sorted(discover_skills(cwd).keys())


def get_skill_info(skill_id: str, cwd: Path | None = None) -> Skill | None:
    skills = discover_skills(cwd)
    return skills.get(skill_id) or skills.get(skill_id.lower())


# ---------------------------------------------------------------------------
# remote registry (ClawHub-like)
# ---------------------------------------------------------------------------

_REMOTE_REGISTRY_URL: str = ""


def set_skill_registry(url: str) -> str:
    global _REMOTE_REGISTRY_URL
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return f"[error] invalid registry URL (http/https required): {url[:100]}"
    _REMOTE_REGISTRY_URL = url
    return f"Registry URL set to: {url}"


def get_registry_url() -> str:
    return _REMOTE_REGISTRY_URL


async def download_skill(skill_id: str) -> str:
    if not _REMOTE_REGISTRY_URL:
        return "[error] no registry URL configured. Use set_skill_registry() first."
    if not skill_id or "/" in skill_id or ".." in skill_id or skill_id.startswith("."):
        return f"[error] invalid skill id: {skill_id!r}"
    try:
        import httpx

        from raven.core.security.ssrf import validate_url

        url = f"{_REMOTE_REGISTRY_URL.rstrip('/')}/skills/{skill_id}"
        error = validate_url(url)
        if error:
            return f"[error] registry URL blocked by SSRF guard: {error}"
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            resp = await client.get(url)
            if resp.is_redirect:
                location = resp.headers.get("Location")
                if location:
                    redirect_error = validate_url(str(resp.url.join(location)))
                    if redirect_error:
                        return f"[error] registry redirect blocked by SSRF guard: {redirect_error}"
            resp.raise_for_status()
            data = resp.json()
        name = data.get("name", skill_id)
        description = data.get("description", "")
        instructions = data.get("instructions", data.get("prompt", ""))
        if not instructions:
            return f"[error] skill '{skill_id}' has no instructions in registry"
        _register_builtin(skill_id, name, description, instructions)
        return f"Downloaded and registered skill: {name}"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return f"[error] skill '{skill_id}' not found in registry"
        return f"[error] registry request failed: {exc}"
    except Exception as exc:
        return f"[error] cannot download skill: {exc}"

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.features import FeatureFlags


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""
    examples: list[str] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    source: str = "local"
    _handler: Callable[..., Any] | None = None

    async def execute(self, *args: object, **kwargs: object) -> Any:
        if self._handler:
            return await self._handler(*args, **kwargs)
        return None


class SkillsRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def register_from_dir(self, path: Path) -> int:
        if not path.is_dir():
            return 0
        count = 0
        skill_file = path / "skill.md"
        if skill_file.exists():
            skill_id = path.name.lower()
            content = skill_file.read_text(encoding="utf-8", errors="replace")
            examples = []
            examples_file = path / "examples.md"
            if examples_file.exists():
                examples = [examples_file.read_text(encoding="utf-8", errors="replace")]
            scripts_dir = path / "scripts"
            paths: list[Path] = [skill_file]
            if scripts_dir.is_dir():
                for sp in sorted(scripts_dir.iterdir()):
                    if sp.suffix in (".py", ".sh", ".ps1"):
                        paths.append(sp)
            description = self._extract_description(content) or f"Skill loaded from {path}"
            skill = Skill(
                name=skill_id,
                description=description,
                instructions=content,
                examples=examples,
                paths=paths,
                source="directory",
            )
            self._skills[skill_id] = skill
            count += 1
        for sub in sorted(path.iterdir()):
            if sub.is_dir() and sub.name != "__pycache__":
                count += self.register_from_dir(sub)
        return count

    def register_builtin(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        return list(self._skills.keys())

    def remove(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None

    def find_by_keyword(self, keyword: str) -> list[Skill]:
        kw = keyword.lower()
        results: list[Skill] = []
        for s in self._skills.values():
            if kw in s.name.lower() or kw in s.description.lower() or kw in s.instructions.lower():
                results.append(s)
        return results

    def _extract_description(self, content: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and len(stripped) > 2:
                return stripped[2:].strip()
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        return lines[0][:120] if lines else ""


skills_registry = SkillsRegistry()

_BUILTIN_SKILLS: dict[str, Skill] = {}
_SKILL_SEARCH_DIRS: tuple[Path, ...] = (
    Path("workspace") / "skills",
    Path(".opencode/skills"),
    Path(".claude/skills"),
    Path(".agents/skills"),
    Path.home() / ".config/opencode/skills",
)


def _register_builtin(id: str, name: str, description: str, instructions: str) -> None:
    _BUILTIN_SKILLS[id] = Skill(name=id, description=description, instructions=instructions)


_register_builtin(
    "security-audit",
    "Security Audit",
    "Review code for common security vulnerabilities (injection, XSS, SSRF, secrets exposure).",
    "Analyze the provided code for:\n- SQL/NoSQL injection\n- Cross-site scripting (XSS)\n- Server-side request forgery (SSRF)\n- Hardcoded secrets/API keys\n- Path traversal\n- Command injection\n\nOutput a report with severity levels.",
)

_register_builtin(
    "code-review",
    "Code Review",
    "Review a pull request or set of changes for correctness, style, and maintainability.",
    "Review the provided diff or code for:\n- Correctness: logic errors, edge cases\n- Style: adherence to project conventions\n- Maintainability: readability, duplication, test coverage\n\nProvide actionable feedback.",
)

_register_builtin(
    "refactor",
    "Refactoring",
    "Refactor code to improve structure, reduce duplication, or modernize patterns.",
    "Analyze the provided code and:\n- Identify duplication\n- Suggest structural improvements\n- Modernize patterns where appropriate\n- Preserve existing behavior\n\nOutput the refactored version.",
)

_register_builtin(
    "test-writer",
    "Test Writer",
    "Write comprehensive tests for code. Prefer real tests over mocks.",
    "Write tests for the provided code:\n- Cover happy path, edge cases, and error paths\n- Prefer real integrations over mocks\n- Use the project's existing test framework\n- Name tests descriptively",
)

_register_builtin(
    "debug",
    "Debugging",
    "Diagnose and fix test failures, runtime errors, or unexpected behavior.",
    "Debug the provided issue:\n- Reproduce the problem\n- Identify root cause\n- Propose a fix\n- Verify the fix doesn't break existing tests",
)

_register_builtin(
    "dependency-update",
    "Dependency Update",
    "Update project dependencies safely check for updates apply and verify compatibility.",
    "Update dependencies:\n- Check current versions\n- Determine compatible updates\n- Apply updates\n- Run tests to verify compatibility",
)


def discover_skills() -> dict[str, Skill]:
    if not FeatureFlags.get().is_enabled("skills"):
        return dict(_BUILTIN_SKILLS)
    result = dict(_BUILTIN_SKILLS)
    for base in _SKILL_SEARCH_DIRS:
        if not base.is_dir():
            continue
        skills_registry.register_from_dir(base)
    for s in skills_registry.list_names():
        skill = skills_registry.get(s)
        if skill:
            result[s] = skill
    return result


SKILLS_DIR = Path("workspace") / "skills"


def ensure_skills_dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def create_skill(name: str, description: str, instructions: str, examples: str = "") -> Path:
    safe_name = name.lower().replace(" ", "-").replace("_", "-")
    skill_dir = SKILLS_DIR / safe_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.md").write_text(f"# {description}\n\n{instructions}", encoding="utf-8")
    if examples:
        (skill_dir / "examples.md").write_text(examples, encoding="utf-8")
    skill = Skill(name=safe_name, description=description, instructions=instructions, source="directory")
    skills_registry.register(skill)
    logger.info("[skills] created '{}' at {}", safe_name, skill_dir)
    return skill_dir


def update_skill(name: str, instructions: str | None = None, description: str | None = None) -> bool:
    skill = skills_registry.get(name)
    if not skill:
        return False
    if instructions is not None:
        skill.instructions = instructions
    if description is not None:
        skill.description = description
    for p in skill.paths:
        if p.name == "skill.md" and p.exists():
            content = p.read_text(encoding="utf-8")
            if instructions is not None:
                content = f"# {skill.description}\n\n{instructions}"
            elif description is not None:
                lines = content.splitlines()
                if lines and lines[0].startswith("# "):
                    lines[0] = f"# {description}"
                content = "\n".join(lines)
            p.write_text(content, encoding="utf-8")
    return True


def list_skills() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in list(_BUILTIN_SKILLS) + skills_registry.list_names():
        if name in seen:
            continue
        seen.add(name)
        skill = _BUILTIN_SKILLS.get(name) or skills_registry.get(name)
        if skill:
            result.append({"name": skill.name, "description": skill.description, "source": skill.source})
    return result


def get_skill_info(name: str) -> Skill | None:
    return _BUILTIN_SKILLS.get(name) or skills_registry.get(name)


def install_skill(source: str) -> Skill | None:
    src_path = Path(source)
    if src_path.is_dir():
        count = skills_registry.register_from_dir(src_path)
        if count > 0:
            logger.info("[skills] installed {} skills from {}", count, source)
            return skills_registry.get(src_path.name.lower())
    elif src_path.is_file() and src_path.suffix == ".md":
        content = src_path.read_text(encoding="utf-8", errors="replace")
        skill_id = src_path.stem.lower()
        first_line = content.splitlines()[0] if content.splitlines() else ""
        description = first_line.lstrip("# ").strip() if first_line.startswith("# ") else skill_id
        skill = Skill(name=skill_id, description=description, instructions=content, source="installed")
        skills_registry.register(skill)
        logger.info("[skills] installed skill '{}' from {}", skill_id, source)
        return skill
    return None


_REMOTE_REGISTRY_URL: str = ""


def set_skill_registry(url: str) -> str:
    global _REMOTE_REGISTRY_URL
    _REMOTE_REGISTRY_URL = url
    logger.info("[skills] remote registry set to {}", url)
    return url


def get_registry_url() -> str:
    return _REMOTE_REGISTRY_URL


async def download_skill(skill_id: str) -> Skill | None:
    if not _REMOTE_REGISTRY_URL:
        logger.warning("[skills] no remote registry configured")
        return None
    import httpx

    url = f"{_REMOTE_REGISTRY_URL.rstrip('/')}/skills/{skill_id}"
    try:
        resp = await httpx.AsyncClient().get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("instructions", "")
        description = data.get("description", skill_id)
        skill = Skill(name=skill_id, description=description, instructions=content, source="remote")
        skills_registry.register(skill)
        return skill
    except Exception:
        logger.opt(exception=True).warning("[skills] failed to download '{}'", skill_id)
        return None

"""ArtifactManager: layered, scoped, lazy artifact resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from raven.core.artifacts import loader
from raven.core.artifacts.model import (
    AgentDef,
    ArtifactContext,
    CommandBundle,
    Rule,
    ScopedSkill,
    ScopeLayer,
)
from raven.core.artifacts.paths import ArtifactPaths
from raven.core.artifacts.scope import ScopeMatcher
from raven.core.artifacts.scope import scope_matcher as _default_matcher

_LAYER_RANK = {
    ScopeLayer.GLOBAL: 1,
    ScopeLayer.TEAM: 2,
    ScopeLayer.LOCAL: 3,
    ScopeLayer.CONFIG: 4,
    ScopeLayer.ENV: 5,
}


class ArtifactManager:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        config: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        matcher: ScopeMatcher | None = None,
        import_agents_md: bool = True,
    ):
        self.cwd = Path(cwd or Path.cwd()).resolve()
        self._resolve_config = config
        self._resolve_env = env
        self._paths = ArtifactPaths.resolve(self.cwd, config, env)
        self._matcher = matcher or _default_matcher
        self._import_agents_md = import_agents_md
        self._public_skills: dict[str, loader.SkillIndex] = {}
        self._public_commands: dict[str, loader.CommandIndex] = {}
        self._public_rules: list[Rule] = []
        self._public_agents: dict[str, AgentDef] = {}
        self._loaded_skills: dict[str, ScopedSkill] = {}
        self._private_skills: dict[str, dict[str, loader.SkillIndex]] = {}
        self._private_commands: dict[str, dict[str, loader.CommandIndex]] = {}
        self._private_rules: dict[str, list[Rule]] = {}
        self.refresh()

    # -- discovery ----------------------------------------------------------

    def refresh(self) -> None:
        self._paths = ArtifactPaths.resolve(self.cwd, self._resolve_config, self._resolve_env)
        self._public_skills = {}
        self._public_commands = {}
        self._public_rules = []
        self._public_agents = {}
        for skill in loader.iter_skills(self._paths.skills):
            self._public_skills.setdefault(skill.name, skill)
        for command in loader.iter_commands(self._paths.commands):
            self._public_commands.setdefault(command.name, command)
        self._public_rules = list(loader.iter_rules(self._paths.rules))
        if self._import_agents_md:
            self._public_rules.extend(loader.import_agents_md(self.cwd))
        for agent in loader.iter_agents(self._paths.agents):
            self._public_agents.setdefault(agent.name, agent)
        self._private_skills.clear()
        self._private_commands.clear()
        self._private_rules.clear()
        self._loaded_skills.clear()
        logger.debug(
            "[artifacts] indexed {} skills, {} commands, {} rules, {} agents",
            len(self._public_skills),
            len(self._public_commands),
            len(self._public_rules),
            len(self._public_agents),
        )

    # -- contexts -----------------------------------------------------------

    def context(
        self,
        *,
        agent_id: str = "default",
        role: str = "",
        channel: str = "",
        command: str | None = None,
        task_type: str | None = None,
        cwd: Path | None = None,
        root: Path | None = None,
        text: str = "",
        extra: dict[str, Any] | None = None,
    ) -> ArtifactContext:
        root = root or self.cwd
        return ArtifactContext(
            agent_id=agent_id,
            role=role,
            channel=channel,
            command=command,
            task_type=task_type,
            cwd=cwd or root,
            root=root,
            text=text,
            extra=extra or {},
        )

    # -- agent private dirs ---------------------------------------------------

    def _private_dirs(self, kind: str, agent_id: str) -> list[Path]:
        dirs: list[Path] = []
        for base in self._paths.agents:
            dirs.append(base / agent_id / kind)
        return [d for d in dirs if d.is_dir()]

    def _skills_for_agent(self, agent_id: str) -> dict[str, loader.SkillIndex]:
        index = dict(self._public_skills)
        private = self._private_skills.get(agent_id)
        if private is None:
            private = {}
            for skill in loader.iter_skills(self._private_dirs("skills", agent_id), ScopeLayer.LOCAL):
                private.setdefault(skill.name, skill)
            self._private_skills[agent_id] = private
        index.update(private)
        return index

    def _commands_for_agent(self, agent_id: str) -> dict[str, loader.CommandIndex]:
        index = dict(self._public_commands)
        private = self._private_commands.get(agent_id)
        if private is None:
            private = {}
            for command in loader.iter_commands(self._private_dirs("commands", agent_id), ScopeLayer.LOCAL):
                private.setdefault(command.name, command)
            self._private_commands[agent_id] = private
        index.update(private)
        return index

    def _rules_for_agent(self, agent_id: str) -> list[Rule]:
        rules = list(self._public_rules)
        private = self._private_rules.get(agent_id)
        if private is None:
            private = list(loader.iter_rules(self._private_dirs("rules", agent_id), ScopeLayer.LOCAL))
            self._private_rules[agent_id] = private
        rules.extend(private)
        return rules

    # -- skills ---------------------------------------------------------------

    def skills_index(self) -> list[loader.SkillIndex]:
        return list(self._public_skills.values())

    def skill_index(self, name: str) -> loader.SkillIndex | None:
        return self._public_skills.get(name)

    def skills_for(self, ctx: ArtifactContext) -> list[ScopedSkill]:
        matched: list[ScopedSkill] = []
        for index in self._skills_for_agent(ctx.agent_id).values():
            if index.activation not in ("auto", "when"):
                continue
            if not self._matcher.match(index.scope, ctx):
                continue
            matched.append(self._load_skill(index))
        matched.sort(key=lambda s: s.name)
        return matched

    def _load_skill(self, index: loader.SkillIndex) -> ScopedSkill:
        cached = self._loaded_skills.get(index.name)
        if cached is not None:
            return cached
        skill = loader.load_skill(index)
        self._loaded_skills[index.name] = skill
        return skill

    # -- commands ---------------------------------------------------------------

    def commands_for(self, ctx: ArtifactContext) -> list[loader.CommandIndex]:
        matched: list[loader.CommandIndex] = []
        for index in self._commands_for_agent(ctx.agent_id).values():
            if not self._matcher.match(index.scope, ctx):
                continue
            matched.append(index)
        matched.sort(key=lambda c: c.name)
        return matched

    def commands_index(self) -> list[loader.CommandIndex]:
        return list(self._public_commands.values())

    def command_index(self, name: str) -> loader.CommandIndex | None:
        return self._public_commands.get(name)

    def load_command(self, index: loader.CommandIndex) -> CommandBundle:
        return loader.load_command(index)

    def command_bundle_for(self, name: str, ctx: ArtifactContext) -> CommandBundle | None:
        index = self._commands_for_agent(ctx.agent_id).get(name)
        if index is None or not self._matcher.match(index.scope, ctx):
            return None
        return self.load_command(index)

    # -- rules ------------------------------------------------------------------

    def rules_for(self, ctx: ArtifactContext) -> list[Rule]:
        matched: list[Rule] = []
        for rule in self._rules_for_agent(ctx.agent_id):
            if not self._rule_applies(rule, ctx):
                continue
            if not self._matcher.match(rule.scope, ctx):
                continue
            matched.append(rule)
        matched.sort(key=lambda r: (_LAYER_RANK.get(r.layer, 2), _depth(r.dir_scope), r.precedence))
        return matched

    def _rule_applies(self, rule: Rule, ctx: ArtifactContext) -> bool:
        if not rule.dir_scope:
            return True
        rel = _rel(ctx.root, ctx.cwd)
        return rel == rule.dir_scope or rel.startswith(rule.dir_scope.rstrip("/") + "/")

    # -- agents ------------------------------------------------------------------

    def agents(self) -> dict[str, AgentDef]:
        return dict(self._public_agents)


def _depth(dir_scope: str) -> int:
    return len([p for p in dir_scope.split("/") if p])


def _rel(root: Path, cwd: Path) -> str:
    try:
        return cwd.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return cwd.name

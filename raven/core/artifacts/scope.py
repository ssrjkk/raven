"""Declarative scope matching for artifacts."""

from __future__ import annotations

from raven.core.artifacts.model import ArtifactContext, ArtifactScope, path_matches, relpath_under


class ScopeMatcher:
    """Decides whether an artifact applies to a given runtime context."""

    def match(self, scope: ArtifactScope, ctx: ArtifactContext) -> bool:
        if not scope.enabled:
            return False
        if scope.agents and ctx.agent_id not in scope.agents:
            return False
        if scope.roles and ctx.role not in scope.roles:
            return False
        if scope.channels and ctx.channel not in scope.channels:
            return False
        if scope.commands and (ctx.command is None or ctx.command not in scope.commands):
            return False
        if scope.task_types and (ctx.task_type is None or ctx.task_type not in scope.task_types):
            return False
        if scope.paths:
            rel = relpath_under(ctx.root, ctx.cwd)
            if not path_matches(scope.paths, rel, ctx.cwd.name):
                return False
        return not (scope.when and not self._when_matches(scope.when, ctx))

    def _when_matches(self, condition: str, ctx: ArtifactContext) -> bool:
        """Match comma-separated keyword phrases against the task text."""
        haystack = (ctx.text or "").lower()
        phrases = [p.strip() for p in condition.split(",") if p.strip()]
        if not phrases:
            return False
        return any(p in haystack for p in phrases)


scope_matcher = ScopeMatcher()

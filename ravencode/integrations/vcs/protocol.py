from __future__ import annotations

from typing import Protocol

from ravencode.integrations.vcs.models import Branch, PullRequest, Repository


class VCSProvider(Protocol):
    """Contract for VCS provider adapters."""

    async def get_repository(self, identifier: str) -> Repository: ...

    async def list_branches(self, identifier: str) -> list[Branch]: ...

    async def create_pull_request(
        self, identifier: str,
        title: str,
        source: str,
        target: str,
        body: str = "",
    ) -> PullRequest: ...

    async def get_file(
        self, identifier: str,
        path: str,
        ref: str | None = None,
    ) -> str | None: ...

    async def create_branch(
        self, identifier: str,
        name: str,
        source: str,
    ) -> bool: ...

    async def create_comment(
        self, identifier: str,
        resource_id: int,
        body: str,
        resource_type: str = "issue",
    ) -> bool: ...

    async def get_pull_request_diff(
        self, identifier: str,
        pr_number: int,
    ) -> str | None: ...

    async def set_commit_status(
        self, identifier: str,
        sha: str,
        state: str,
        description: str,
        context: str = "ravencode/ci",
    ) -> bool: ...

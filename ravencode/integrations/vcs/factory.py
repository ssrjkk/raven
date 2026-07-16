from __future__ import annotations

from ravencode.integrations.vcs.github_provider import GitHubProvider
from ravencode.integrations.vcs.gitlab_provider import GitLabProvider


def create_vcs_provider(provider_type: str, token: str | None = None, **kwargs: str) -> GitHubProvider | GitLabProvider:
    if provider_type == "github":
        return GitHubProvider(token=token, api_url=kwargs.get("api_url", "https://api.github.com"))
    elif provider_type == "gitlab":
        return GitLabProvider(token=token, api_url=kwargs.get("api_url", ""))
    else:
        raise ValueError(f"Unknown VCS provider: {provider_type}")

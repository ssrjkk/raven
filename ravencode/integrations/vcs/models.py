from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Repository:
    name: str
    full_name: str
    default_branch: str
    private: bool


@dataclass
class Branch:
    name: str
    commit_sha: str
    protected: bool


@dataclass
class PullRequest:
    id: int
    title: str
    source_branch: str
    target_branch: str
    url: str
    body: str = ""
    state: str = "open"

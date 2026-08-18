from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from ravencode.integrations.base import CIProvider
from ravencode.integrations.github import GitHubIntegration, parse_github_webhook
from ravencode.integrations.gitlab import (
    GitLabIntegration,
    parse_gitlab_webhook,
    parse_gitlab_webhook_request,
)
from ravencode.integrations.models import EventContext, EventType, WorkflowResult
from ravencode.integrations.vcs.factory import create_vcs_provider
from ravencode.integrations.vcs.github_provider import GitHubProvider
from ravencode.integrations.vcs.github_webhook import GitHubLegacyNormalizer, GitHubWebhookNormalizer
from ravencode.integrations.vcs.gitlab_provider import GitLabProvider
from ravencode.integrations.vcs.gitlab_webhook import GitLabLegacyNormalizer, GitLabWebhookNormalizer
from ravencode.integrations.vcs.webhook import (
    WebhookEvent,
    WebhookEventType,
    parse_legacy_webhook,
    parse_webhook,
    webhook_event_to_context,
)


def make_request(body: bytes, headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock(spec=Request)
    req.body = AsyncMock(return_value=body)
    req.headers = headers or {}
    return req


class TestModels:
    def test_full_name(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="github", repo="r", owner="o")
        assert ctx.full_name == "o/r"

    def test_workflow_result_defaults(self) -> None:
        wf = WorkflowResult(success=True, summary="ok")
        assert wf.actions == []
        assert wf.error is None


class FakeProvider(CIProvider):
    def __init__(self) -> None:
        super().__init__()
        self.comment_called: list[str] = []

    async def _handle_issue_comment(self, ctx: EventContext) -> WorkflowResult | None:
        self.comment_called.append(ctx.comment_body or "")
        return WorkflowResult(success=True, summary="handled comment")

    async def _handle_pr_opened(self, ctx: EventContext) -> WorkflowResult | None:
        return WorkflowResult(success=True, summary="handled pr")

    async def _handle_issue_opened(self, ctx: EventContext) -> WorkflowResult | None:
        return WorkflowResult(success=True, summary="handled issue")

    async def _handle_pr_review(self, ctx: EventContext) -> WorkflowResult | None:
        return WorkflowResult(success=True, summary="handled review")

    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        return True

    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        return None

    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        return True

    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        return 1

    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        return "diff"

    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        return True


class TestCIProviderRouting:
    def _ctx(self, event_type: EventType, **kw) -> EventContext:
        return EventContext(event_type=event_type, platform="github", repo="r", owner="o", **kw)

    async def test_issue_comment_route(self) -> None:
        p = FakeProvider()
        result = await p.handle_event(self._ctx(EventType.ISSUE_COMMENT, comment_body="hi"))
        assert result is not None
        assert result.summary == "handled comment"
        assert p.comment_called == ["hi"]

    async def test_pr_opened_route(self) -> None:
        p = FakeProvider()
        result = await p.handle_event(self._ctx(EventType.PR_OPENED))
        assert result is not None
        assert result.summary == "handled pr"

    async def test_issue_opened_route(self) -> None:
        p = FakeProvider()
        result = await p.handle_event(self._ctx(EventType.ISSUE_OPENED))
        assert result is not None
        assert result.summary == "handled issue"

    async def test_pr_review_route(self) -> None:
        p = FakeProvider()
        result = await p.handle_event(self._ctx(EventType.PR_REVIEW_REQUESTED))
        assert result is not None
        assert result.summary == "handled review"

    async def test_unhandled_event_returns_none(self) -> None:
        p = FakeProvider()
        assert await p.handle_event(self._ctx(EventType.PUSH)) is None


class MinimalProvider(CIProvider):
    async def post_comment(self, ctx: EventContext, body: str) -> bool:
        return True

    async def get_file_content(self, ctx: EventContext, path: str, ref: str | None = None) -> str | None:
        return None

    async def create_branch(self, ctx: EventContext, base: str, head: str) -> bool:
        return True

    async def create_pr(self, ctx: EventContext, title: str, body: str, head: str, base: str) -> int | None:
        return 1

    async def get_pr_diff(self, ctx: EventContext, pr_number: int) -> str | None:
        return None

    async def set_commit_status(self, ctx: EventContext, sha: str, state: str, description: str) -> bool:
        return True


class TestCIProviderDefaultHandlers:
    def _ctx(self, event_type: EventType, **kw) -> EventContext:
        return EventContext(event_type=event_type, platform="github", repo="r", owner="o", **kw)

    async def test_default_issue_comment_handler(self) -> None:
        assert await MinimalProvider().handle_event(self._ctx(EventType.ISSUE_COMMENT, comment_body="hi")) is None

    async def test_default_pr_opened_handler(self) -> None:
        assert await MinimalProvider().handle_event(self._ctx(EventType.PR_OPENED)) is None

    async def test_default_issue_opened_handler(self) -> None:
        assert await MinimalProvider().handle_event(self._ctx(EventType.ISSUE_OPENED)) is None

    async def test_default_pr_review_handler(self) -> None:
        assert await MinimalProvider().handle_event(self._ctx(EventType.PR_REVIEW_REQUESTED)) is None


class TestGitLabIntegration:
    async def test_no_provider_methods(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="gitlab", repo="r", owner="o")
        integration = GitLabIntegration(token=None)
        assert integration._provider is None

        assert await integration.post_comment(ctx, "b") is False
        assert await integration.get_file_content(ctx, "x") is None
        assert await integration.create_branch(ctx, "main", "feat") is False
        assert await integration.create_pr(ctx, "t", "b", "feat", "main") is None
        assert await integration.get_pr_diff(ctx, 1) is None
        assert await integration.set_commit_status(ctx, "s", "success", "d") is False

    async def test_with_provider(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="gitlab", repo="r", owner="o", pr_number=2)
        provider = MagicMock()
        provider.create_comment = AsyncMock(return_value=True)
        provider.get_file = AsyncMock(return_value="content")
        provider.create_branch = AsyncMock(return_value=True)
        provider.create_pull_request = AsyncMock(return_value=MagicMock(id=7))
        provider.get_pull_request_diff = AsyncMock(return_value="diff")
        provider.set_commit_status = AsyncMock(return_value=True)
        integration = GitLabIntegration(token="t")
        integration._provider = provider

        assert await integration.post_comment(ctx, "b") is True
        assert await integration.get_file_content(ctx, "f", "main") == "content"
        assert await integration.create_branch(ctx, "main", "feat") is True
        assert await integration.create_pr(ctx, "t", "b", "feat", "main") == 7
        assert await integration.get_pr_diff(ctx, 3) == "diff"
        assert await integration.set_commit_status(ctx, "s", "ok", "d") is True

    async def test_with_provider_no_rid(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="gitlab", repo="r", owner="o")
        integration = GitLabIntegration(token="t")
        integration._provider = MagicMock()
        assert await integration.post_comment(ctx, "b") is False

    async def test_with_provider_no_owner(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="gitlab", repo="r", owner="", pr_number=1)
        provider = MagicMock()
        provider.create_comment = AsyncMock(return_value=True)
        integration = GitLabIntegration(token="t")
        integration._provider = provider
        assert await integration.post_comment(ctx, "b") is True
        provider.create_comment.assert_called_once_with("r", 1, "b")

    def test_parse_gitlab_webhook(self) -> None:
        payload = {
            "project": {"path_with_namespace": "g/p"},
            "object_attributes": {"iid": 3},
            "user": {"username": "dev"},
        }
        ctx = parse_gitlab_webhook("Issue Hook", payload)
        assert ctx is not None
        assert ctx.platform == "gitlab"
        assert ctx.event_type == EventType.ISSUE_OPENED
        assert parse_gitlab_webhook("Unknown", {}) is None

    async def test_parse_gitlab_webhook_request(self) -> None:
        ev = WebhookEvent(event_type=WebhookEventType.PUSH, repository="g/p", actor="a", payload={})
        with patch("ravencode.integrations.gitlab.parse_webhook", AsyncMock(return_value=ev)):
            result = await parse_gitlab_webhook_request(make_request(b"{}"), "secret")
        assert result is ev


class TestVcsFactory:
    def test_github(self) -> None:
        provider = create_vcs_provider("github", token="t")
        assert isinstance(provider, GitHubProvider)
        assert provider._token == "t"

    def test_gitlab(self) -> None:
        provider = create_vcs_provider("gitlab", token="t", api_url="https://git.example.com")
        assert isinstance(provider, GitLabProvider)
        assert provider._token == "t"
        assert provider._api_url == "https://git.example.com/api/v4"

    def test_gitlab_default_url(self) -> None:
        provider = create_vcs_provider("gitlab")
        assert provider._api_url == "https://gitlab.com/api/v4"

    def test_unknown_provider(self) -> None:
        with pytest.raises(ValueError, match="Unknown VCS provider: bitbucket"):
            create_vcs_provider("bitbucket")


class TestGitHubWebhookNormalizer:
    def _signed(self, body: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_validate_signature_ok(self) -> None:
        body = b'{"x": 1}'
        n = GitHubWebhookNormalizer()
        assert n.validate_signature({"X-Hub-Signature-256": self._signed(body, "s")}, body, "s") is True

    def test_validate_signature_bad_prefix(self) -> None:
        n = GitHubWebhookNormalizer()
        assert n.validate_signature({"X-Hub-Signature-256": "sha1=abc"}, b"x", "s") is False

    def test_validate_signature_mismatch(self) -> None:
        n = GitHubWebhookNormalizer()
        assert n.validate_signature({"X-Hub-Signature-256": "sha256=deadbeef"}, b"x", "s") is False

    def test_normalize_push(self) -> None:
        payload = {
            "ref": "refs/heads/main",
            "pusher": {"name": "alice"},
            "repository": {"full_name": "o/r"},
        }
        ev = GitHubWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PUSH
        assert ev.repository == "o/r"
        assert ev.actor == "alice"
        assert ev.ref == "refs/heads/main"

    def test_normalize_pull_request_opened(self) -> None:
        payload = {
            "action": "opened",
            "repository": {"full_name": "o/r"},
            "pull_request": {"user": {"login": "bob"}, "head": {"ref": "feat"}},
        }
        ev = GitHubWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PULL_REQUEST_OPENED

    def test_normalize_pull_request_closed(self) -> None:
        payload = {
            "action": "closed",
            "repository": {"full_name": "o/r"},
            "pull_request": {"user": {"login": "bob"}, "head": {"ref": "feat"}},
        }
        ev = GitHubWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PULL_REQUEST_CLOSED

    def test_normalize_issue_opened(self) -> None:
        payload = {
            "action": "opened",
            "repository": {"full_name": "o/r"},
            "issue": {"user": {"login": "carol"}},
        }
        ev = GitHubWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.ISSUE_OPENED

    def test_normalize_unsupported_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            GitHubWebhookNormalizer().normalize({"repository": {}})


class TestGitLabWebhookNormalizer:
    def test_validate_signature(self) -> None:
        n = GitLabWebhookNormalizer()
        assert n.validate_signature({"X-Gitlab-Token": "tok"}, b"x", "tok") is True
        assert n.validate_signature({"X-Gitlab-Token": "bad"}, b"x", "tok") is False
        assert n.validate_signature({"X-Gitlab-Token": "tok"}, b"x", "") is False

    def test_normalize_push(self) -> None:
        payload = {
            "object_kind": "push",
            "project": {"path_with_namespace": "g/p"},
            "user_username": "dev",
            "ref": "main",
        }
        ev = GitLabWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PUSH
        assert ev.actor == "dev"

    def test_normalize_merge_request_open(self) -> None:
        payload = {
            "object_kind": "merge_request",
            "project": {"path_with_namespace": "g/p"},
            "object_attributes": {"action": "open", "author_id": 7, "source_branch": "f"},
        }
        ev = GitLabWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PULL_REQUEST_OPENED

    def test_normalize_merge_request_closed(self) -> None:
        payload = {
            "object_kind": "merge_request",
            "project": {"path_with_namespace": "g/p"},
            "object_attributes": {"action": "close", "author_id": 7, "source_branch": "f"},
        }
        ev = GitLabWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.PULL_REQUEST_CLOSED

    def test_normalize_issue(self) -> None:
        payload = {
            "object_kind": "issue",
            "project": {"path_with_namespace": "g/p"},
            "object_attributes": {"action": "open", "author_id": 9},
        }
        ev = GitLabWebhookNormalizer().normalize(payload)
        assert ev.event_type == WebhookEventType.ISSUE_OPENED

    def test_normalize_unsupported_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported GitLab"):
            GitLabWebhookNormalizer().normalize({"object_kind": "pipeline"})


class TestParseWebhook:
    def _gh_body(self, secret: str) -> tuple[bytes, str]:
        body = json.dumps({"ref": "main", "pusher": {"name": "a"}, "repository": {"full_name": "o/r"}}).encode()
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return body, f"sha256={digest}"

    async def test_parse_webhook_ok(self) -> None:
        body, sig = self._gh_body("s")
        req = make_request(body, {"X-Hub-Signature-256": sig})
        ev = await parse_webhook(GitHubWebhookNormalizer(), req, "s")
        assert ev.event_type == WebhookEventType.PUSH

    async def test_parse_webhook_bad_signature(self) -> None:
        body, _ = self._gh_body("s")
        req = make_request(body, {"X-Hub-Signature-256": "sha256=bad"})
        with pytest.raises(ValueError, match="signature"):
            await parse_webhook(GitHubWebhookNormalizer(), req, "s")

    async def test_parse_webhook_bad_json(self) -> None:
        class AlwaysValid:
            def validate_signature(self, headers: dict[str, str], body: bytes, secret: str) -> bool:
                return True

            def normalize(self, raw_payload):  # pragma: no cover
                return None

        req = make_request(b"not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            await parse_webhook(AlwaysValid(), req, "s")


class TestWebhookEventToContext:
    def _event(self, event_type: WebhookEventType) -> WebhookEvent:
        return WebhookEvent(event_type=event_type, repository="o/r", actor="a", payload={}, ref="main")

    def test_push(self) -> None:
        ctx = webhook_event_to_context(self._event(WebhookEventType.PUSH))
        assert ctx.event_type == EventType.PUSH

    def test_pr_opened_closed(self) -> None:
        ctx = webhook_event_to_context(self._event(WebhookEventType.PULL_REQUEST_OPENED))
        assert ctx.event_type == EventType.PR_OPENED
        ctx = webhook_event_to_context(self._event(WebhookEventType.PULL_REQUEST_CLOSED))
        assert ctx.event_type == EventType.PR_OPENED

    def test_pr_comment(self) -> None:
        ctx = webhook_event_to_context(self._event(WebhookEventType.PULL_REQUEST_COMMENT))
        assert ctx.event_type == EventType.PR_COMMENT

    def test_issue_opened_closed(self) -> None:
        ctx = webhook_event_to_context(self._event(WebhookEventType.ISSUE_OPENED))
        assert ctx.event_type == EventType.ISSUE_OPENED
        ctx = webhook_event_to_context(self._event(WebhookEventType.ISSUE_CLOSED))
        assert ctx.event_type == EventType.ISSUE_OPENED

    def test_issue_comment(self) -> None:
        ctx = webhook_event_to_context(self._event(WebhookEventType.ISSUE_COMMENT))
        assert ctx.event_type == EventType.ISSUE_COMMENT

    def test_owner_repo_split(self) -> None:
        ev = WebhookEvent(event_type=WebhookEventType.PUSH, repository="owner/my-repo", actor="a", payload={})
        ctx = webhook_event_to_context(ev)
        assert ctx.owner == "owner"
        assert ctx.repo == "my-repo"


class TestParseLegacyWebhook:
    def test_github_issue(self) -> None:
        payload = {
            "repository": {"full_name": "o/r"},
            "issue": {"number": 5, "title": "T", "body": "B"},
            "sender": {"login": "u"},
        }
        ctx = parse_legacy_webhook(GitHubLegacyNormalizer(), "issues", payload)
        assert ctx is not None
        assert ctx.event_type == EventType.ISSUE_OPENED
        assert ctx.issue_number == 5
        assert ctx.title == "T"
        assert ctx.body == "B"

    def test_github_issue_comment(self) -> None:
        payload = {
            "repository": {"full_name": "o/r"},
            "issue": {"number": 5},
            "comment": {"id": 11, "body": "note"},
        }
        ctx = parse_legacy_webhook(GitHubLegacyNormalizer(), "issue_comment", payload)
        assert ctx is not None
        assert ctx.comment_id == 11
        assert ctx.comment_body == "note"

    def test_github_pr(self) -> None:
        payload = {"repository": {"full_name": "o/r"}, "pull_request": {"number": 8, "title": "PR", "body": "B"}}
        ctx = parse_legacy_webhook(GitHubLegacyNormalizer(), "pull_request", payload)
        assert ctx is not None
        assert ctx.pr_number == 8

    def test_github_pr_comment(self) -> None:
        payload = {
            "repository": {"full_name": "o/r"},
            "pull_request": {"number": 8},
            "comment": {"id": 12, "body": "review note"},
        }
        ctx = parse_legacy_webhook(GitHubLegacyNormalizer(), "pull_request_review_comment", payload)
        assert ctx is not None
        assert ctx.pr_number == 8
        assert ctx.comment_body == "review note"

    def test_unknown_event_returns_none(self) -> None:
        assert parse_legacy_webhook(GitHubLegacyNormalizer(), "weird", {}) is None

    def test_gitlab_legacy_detect(self) -> None:
        n = GitLabLegacyNormalizer()
        assert n.detect_event_type("Issue Hook", {}) == EventType.ISSUE_OPENED
        assert n.detect_event_type("Merge Request Hook", {}) == EventType.MERGE_REQUEST_OPENED
        assert (
            n.detect_event_type("Note Hook", {"object_attributes": {"noteable_type": "MergeRequest"}})
            == EventType.MERGE_REQUEST_COMMENT
        )
        assert n.detect_event_type("Note Hook", {}) == EventType.ISSUE_COMMENT
        assert n.detect_event_type("Unknown", {}) is None

    def test_gitlab_legacy_extractors(self) -> None:
        n = GitLabLegacyNormalizer()
        payload = {
            "project": {"path_with_namespace": "g/p"},
            "user": {"username": "dev"},
            "object_attributes": {
                "iid": 3,
                "title": "T",
                "description": "D",
                "id": 9,
                "note": "N",
                "last_commit": {"id": "sha1"},
            },
            "merge_request": {"iid": 4, "title": "MR"},
        }
        assert n.get_owner(payload) == "g"
        assert n.get_repo(payload) == "p"
        assert n.get_sender(payload) == "dev"
        assert n.get_sha(payload) == "sha1"
        assert n.get_sha({"object_attributes": {}}) is None
        assert n.extract_issue(payload)["iid"] == 3
        assert n.extract_comment(payload)["note"] == "N"
        assert n.extract_pr(payload)["iid"] == 4


class TestGitHubIntegration:
    def test_no_provider_methods(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="github", repo="r", owner="o")
        integration = GitHubIntegration(token=None)
        assert not integration._provider

        async def run() -> None:
            assert await integration.post_comment(ctx, "b") is False
            assert await integration.get_file_content(ctx, "x") is None
            assert await integration.create_branch(ctx, "main", "feat") is False
            assert await integration.create_pr(ctx, "t", "b", "feat", "main") is None
            assert await integration.get_pr_diff(ctx, 1) is None
            assert await integration.set_commit_status(ctx, "s", "success", "d") is False

        import asyncio

        asyncio.run(run())

    async def test_with_provider(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="github", repo="r", owner="o", pr_number=1)
        provider = MagicMock()
        provider.create_comment = AsyncMock(return_value=True)
        provider.get_file = AsyncMock(return_value="content")
        provider.create_branch = AsyncMock(return_value=True)
        provider.create_pull_request = AsyncMock(return_value=MagicMock(id=42))
        provider.get_pull_request_diff = AsyncMock(return_value="diff")
        provider.set_commit_status = AsyncMock(return_value=True)
        integration = GitHubIntegration(token="t")
        integration._provider = provider

        assert await integration.post_comment(ctx, "b") is True
        assert await integration.get_file_content(ctx, "f", "main") == "content"
        assert await integration.create_branch(ctx, "main", "feat") is True
        assert await integration.create_pr(ctx, "t", "b", "feat", "main") == 42
        assert await integration.get_pr_diff(ctx, 3) == "diff"
        assert await integration.set_commit_status(ctx, "s", "ok", "d") is True

    async def test_with_provider_no_issue_number(self) -> None:
        ctx = EventContext(event_type=EventType.PUSH, platform="github", repo="r", owner="o")
        provider = MagicMock()
        integration = GitHubIntegration(token="t")
        integration._provider = provider
        assert await integration.post_comment(ctx, "b") is False

    def test_parse_github_webhook(self) -> None:
        payload = {"repository": {"full_name": "o/r"}, "push": {}}
        ctx = parse_github_webhook("push", payload)
        assert ctx is not None
        assert ctx.platform == "github"
        assert parse_github_webhook("nope", payload) is None


class TestGitHubProvider:
    async def test_init_with_token(self) -> None:
        provider = GitHubProvider(token="abc", api_url="https://api.github.com/")
        assert provider._api_url == "https://api.github.com"
        assert "Authorization" in provider._headers
        assert provider._headers["Authorization"] == "Bearer abc"

    async def test_get_repository(self) -> None:
        provider = GitHubProvider(token="t")
        resp = MagicMock()
        resp.json.return_value = {"name": "r", "full_name": "o/r", "default_branch": "main", "private": False}
        provider._request = AsyncMock(return_value=resp)  # type: ignore[method-assign]
        repo = await provider.get_repository("o/r")
        assert repo.full_name == "o/r"

    async def test_list_branches(self) -> None:
        provider = GitHubProvider(token="t")
        resp = MagicMock()
        resp.json.return_value = [{"name": "main", "commit": {"sha": "s1"}, "protected": True}]
        provider._request = AsyncMock(return_value=resp)  # type: ignore[method-assign]
        branches = await provider.list_branches("o/r")
        assert branches[0].name == "main"

    async def test_get_file_not_found(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        provider._request = AsyncMock(side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock()))  # type: ignore[method-assign]
        assert await provider.get_file("o/r", "missing.py") is None

    async def test_create_branch_success_and_failure(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        resp = MagicMock()
        resp.json.return_value = {"object": {"sha": "abc"}}
        provider._request = AsyncMock(side_effect=[resp, resp])  # type: ignore[method-assign]
        assert await provider.create_branch("o/r", "f", "main") is True

        provider._request = AsyncMock(side_effect=httpx.HTTPStatusError("x", request=MagicMock(), response=MagicMock()))  # type: ignore[method-assign]
        assert await provider.create_branch("o/r", "f", "main") is False

    async def test_create_comment_success_and_failure(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        provider._request = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        assert await provider.create_comment("o/r", 1, "body") is True

        provider._request = AsyncMock(side_effect=httpx.HTTPStatusError("x", request=MagicMock(), response=MagicMock()))  # type: ignore[method-assign]
        assert await provider.create_comment("o/r", 1, "body") is False

    async def test_set_commit_status_and_close_issue(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        provider._request = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        assert await provider.set_commit_status("o/r", "s", "ok", "d") is True
        assert await provider.close_issue("o/r", 1) is True
        provider._request = AsyncMock(side_effect=httpx.HTTPStatusError("x", request=MagicMock(), response=MagicMock()))  # type: ignore[method-assign]
        assert await provider.set_commit_status("o/r", "s", "ok", "d") is False
        assert await provider.close_issue("o/r", 1) is False

    async def test_get_issue_and_labels(self) -> None:
        provider = GitHubProvider(token="t")
        resp = MagicMock()
        resp.json.return_value = {"number": 1}
        provider._request = AsyncMock(return_value=resp)  # type: ignore[method-assign]
        assert await provider.get_issue("o/r", 1) == {"number": 1}

        resp2 = MagicMock()
        resp2.json.return_value = [{"name": "bug"}]
        provider._request = AsyncMock(return_value=resp2)  # type: ignore[method-assign]
        assert await provider.get_repo_labels("o/r") == ["bug"]

    async def test_add_labels(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        provider._request = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
        assert await provider.add_labels("o/r", 1, ["bug"]) is True
        provider._request = AsyncMock(side_effect=httpx.HTTPStatusError("x", request=MagicMock(), response=MagicMock()))  # type: ignore[method-assign]
        assert await provider.add_labels("o/r", 1, ["bug"]) is False

    async def test_get_pull_request_diff(self) -> None:
        import httpx

        provider = GitHubProvider(token="t")
        resp = MagicMock()
        resp.text = "diff text"
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        with patch("ravencode.integrations.vcs.github_provider.httpx.AsyncClient", return_value=client):
            assert await provider.get_pull_request_diff("o/r", 1) == "diff text"


class TestGitLabProvider:
    async def test_init(self) -> None:
        provider = GitLabProvider(token="t")
        assert provider._token == "t"


class TestGitHubWebhookApp:
    @pytest.fixture
    def integration(self):
        return MagicMock()

    @pytest.fixture
    def ghw_module(self):
        import ravencode.integrations.github_webhook as mod

        return mod

    def _event(self, event_type: WebhookEventType, comment_body: str = "") -> WebhookEvent:
        return WebhookEvent(event_type=event_type, repository="o/r", actor="a", payload={"comment": {"body": comment_body}})

    async def test_health(self, ghw_module) -> None:
        app = ghw_module.app
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "ok"}

    async def test_handler_value_error(self, ghw_module) -> None:
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            side_effect=ValueError("bad signature"),
        ):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc:
                await ghw_module.webhook_handler(make_request(b"{}"))
            assert exc.value.status_code == 400

    async def test_handler_not_initialized(self, ghw_module) -> None:
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            return_value=self._event(WebhookEventType.PUSH),
        ), patch("ravencode.integrations.github_webhook._integration", None):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc:
                await ghw_module.webhook_handler(make_request(b"{}"))
            assert exc.value.status_code == 500

    async def test_handler_ignored_comment(self, ghw_module, integration) -> None:
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            return_value=self._event(WebhookEventType.ISSUE_COMMENT, comment_body="just a comment"),
        ), patch("ravencode.integrations.github_webhook._integration", integration):
            result = await ghw_module.webhook_handler(make_request(b"{}"))
        assert result == {"status": "ignored", "reason": "Not a ravencode command"}
        integration.handle_event.assert_not_called()

    async def test_handler_processed_comment(self, ghw_module, integration) -> None:
        integration.handle_event = AsyncMock(return_value=WorkflowResult(success=True, summary="done"))
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            return_value=self._event(WebhookEventType.PULL_REQUEST_COMMENT, comment_body="/ravencode run tests"),
        ), patch("ravencode.integrations.github_webhook._integration", integration):
            result = await ghw_module.webhook_handler(make_request(b"{}"))
        assert result["status"] == "processed"
        assert result["result"] == "done"

    async def test_handler_processed_push(self, ghw_module, integration) -> None:
        integration.handle_event = AsyncMock(return_value=WorkflowResult(success=True, summary="pushed"))
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            return_value=self._event(WebhookEventType.PUSH),
        ), patch("ravencode.integrations.github_webhook._integration", integration):
            result = await ghw_module.webhook_handler(make_request(b"{}"))
        assert result["status"] == "processed"

    async def test_handler_no_result(self, ghw_module, integration) -> None:
        integration.handle_event = AsyncMock(return_value=None)
        with patch(
            "ravencode.integrations.github_webhook.parse_github_webhook_request",
            new_callable=AsyncMock,
            return_value=self._event(WebhookEventType.PUSH),
        ), patch("ravencode.integrations.github_webhook._integration", integration):
            result = await ghw_module.webhook_handler(make_request(b"{}"))
        assert result["result"] == "No action"

    async def test_run_webhook_server(self, ghw_module) -> None:
        with patch("ravencode.integrations.github_webhook.uvicorn.run") as run_mock:
            ghw_module.run_webhook_server(host="127.0.0.1", port=9000, token="t", secret="s")
        run_mock.assert_called_once()
        assert ghw_module._integration is not None
        assert ghw_module._webhook_secret == "s"

    async def test_run_webhook_server_default_secret(self, ghw_module, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
        with patch("ravencode.integrations.github_webhook.uvicorn.run"):
            ghw_module.run_webhook_server(token="t")
        assert ghw_module._webhook_secret == ""

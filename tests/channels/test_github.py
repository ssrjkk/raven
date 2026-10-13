from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.github.channel import GithubChannel
from raven.core.models import Message


def _channel_with_handler() -> tuple[GithubChannel, AsyncMock]:
    handler = AsyncMock()
    c = GithubChannel()
    return c, handler


@pytest.mark.asyncio
async def test_github_start_stop():
    c = GithubChannel()
    await c.start()
    assert c._ready
    await c.stop()
    assert not c._ready
    assert c._token == ""


@pytest.mark.asyncio
async def test_github_webhook_requires_handler_and_ready():
    c = GithubChannel()
    assert not await c.handle_webhook({"repository": {"full_name": "o/r"}}, {"x-github-event": "push"})


@pytest.mark.asyncio
async def test_github_push_event():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "ref": "refs/heads/main",
        "commits": [{"message": "feat: thing"}, {"message": "fix: other"}],
        "pusher": {"name": "pusher"},
        "repository": {"full_name": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "push"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "github"
    assert event.text == "feat: thing"
    assert event.session_id == "github:acme/app:push:main"
    assert event.metadata["commit_count"] == 2


@pytest.mark.asyncio
async def test_github_push_empty_commits_falls_back():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {"ref": "refs/heads/dev", "commits": [], "sender": {"login": "s"}, "repository": {"full_name": "o/r"}}
    assert await c.handle_webhook(body, {"x-github-event": "push"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Pushed to dev"
    assert event.user_id == "s"


@pytest.mark.asyncio
async def test_github_pull_request_event():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "action": "opened",
        "pull_request": {
            "title": "Add X", "body": "because", "number": 7,
            "user": {"login": "author"}, "head": {"ref": "feature"},
        },
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "pull_request"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "PR opened: Add X\nbecause"
    assert event.session_id == "github:o/r:pr:7"
    assert event.metadata["ref"] == "feature"


@pytest.mark.asyncio
async def test_github_pull_request_without_body():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {"action": "closed", "pull_request": {"title": "T", "number": 1}, "repository": {"full_name": "o/r"}}
    assert await c.handle_webhook(body, {"x-github-event": "pull_request"})
    assert handler.await_args[0][0].text == "PR closed: T"  # type: ignore[index]


@pytest.mark.asyncio
async def test_github_issues_event():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "action": "opened",
        "issue": {"title": "Bug", "body": "details", "number": 3, "user": {"login": "u"}},
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "issues"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Issue opened: Bug\ndetails"
    assert event.metadata["issue_number"] == 3


@pytest.mark.asyncio
async def test_github_comment_events():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "issue": {"number": 9},
        "comment": {"body": "nice", "user": {"login": "c"}},
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "issue_comment"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "nice"
    assert event.session_id == "github:o/r:comment:9"

    body2 = {
        "pull_request": {"number": 4},
        "comment": {"user": {"login": "c"}},
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body2, {"x-github-event": "pull_request_review_comment"})
    assert handler.await_args[0][0].text == "Comment on #4"  # type: ignore[index]


@pytest.mark.asyncio
async def test_github_review_event():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "pull_request": {"number": 2},
        "review": {"state": "approved", "body": "LGTM", "user": {"login": "r"}},
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "pull_request_review"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Review approved: LGTM"
    assert event.metadata["review_state"] == "approved"


@pytest.mark.asyncio
async def test_github_workflow_run_event():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    body = {
        "action": "completed",
        "workflow_run": {"name": "CI", "status": "completed", "conclusion": "failure"},
        "sender": {"login": "gh"},
        "repository": {"full_name": "o/r"},
    }
    assert await c.handle_webhook(body, {"x-github-event": "workflow_run"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Workflow completed: CI (failure)"
    assert event.session_id == "github:o/r:workflow:CI"


@pytest.mark.asyncio
async def test_github_unknown_event_is_false():
    c, handler = _channel_with_handler()
    await c.on_message(handler)
    await c.start()
    assert not await c.handle_webhook({"repository": {"full_name": "o/r"}}, {"x-github-event": "star"})
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_github_send_issue_comment(monkeypatch: pytest.MonkeyPatch):
    c = GithubChannel()
    await c.start()
    c._token = "tok"
    post = AsyncMock()
    monkeypatch.setattr("raven.channels.github.channel.client_manager.post", post)
    msg = Message(session_id="github:acme/app:issue:12", channel="github", role="assistant", content="reply")
    await c.send("github:acme/app:issue:12", msg)
    url = post.await_args[0][0]  # type: ignore[index]
    assert url == "https://api.github.com/repos/acme/app/issues/12/comments"
    assert post.await_args.kwargs["json"]["body"] == "reply"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_github_send_skips_without_token_or_shape(monkeypatch: pytest.MonkeyPatch):
    c = GithubChannel()
    await c.start()
    c._token = ""
    post = AsyncMock()
    monkeypatch.setattr("raven.channels.github.channel.client_manager.post", post)
    msg = Message(session_id="x", channel="github", role="assistant", content="r")
    await c.send("github:acme/app:issue:12", msg)   # no token
    await c.send("short", msg)                       # malformed session id
    await c.send("github:acme/app:pr:1", msg)        # not an issue target
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_github_send_error_is_swallowed(monkeypatch: pytest.MonkeyPatch):
    c = GithubChannel()
    await c.start()
    c._token = "tok"
    post = AsyncMock(side_effect=RuntimeError("network"))
    monkeypatch.setattr("raven.channels.github.channel.client_manager.post", post)
    msg = Message(session_id="github:o/r:issue:1", channel="github", role="assistant", content="r")
    await c.send("github:o/r:issue:1", msg)

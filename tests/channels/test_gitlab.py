from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from raven.channels.gitlab.channel import GitlabChannel
from raven.core.models import Message


def _ready_channel() -> tuple[GitlabChannel, AsyncMock]:
    handler = AsyncMock()
    c = GitlabChannel()
    return c, handler


@pytest.mark.asyncio
async def test_gitlab_start_stop():
    c = GitlabChannel()
    await c.start()
    assert c._ready
    assert c._gitlab_url
    await c.stop()
    assert not c._ready


@pytest.mark.asyncio
async def test_gitlab_webhook_requires_handler_and_ready():
    c = GitlabChannel()
    assert not await c.handle_webhook({"object_kind": "push"}, {"x-gitlab-event": "Push Hook"})


@pytest.mark.asyncio
async def test_gitlab_push_hook():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "push",
        "message": "feat: x",
        "user_id": 5,
        "ref": "refs/heads/main",
        "commits": [{"message": "a"}, {"message": "b"}],
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Push Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.channel == "gitlab"
    assert event.text == "feat: x"
    assert event.session_id == "gitlab:42:5"
    assert event.metadata["commit_count"] == 2
    assert event.metadata["ref"] == "main"


@pytest.mark.asyncio
async def test_gitlab_push_hook_message_fallbacks():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    base = {"object_kind": "push", "ref": "refs/heads/dev", "project": {"id": 1, "path": "p"}}
    assert await c.handle_webhook({**base, "commits": [{"message": "from commit"}], "user_username": "uu"}, {"x-gitlab-event": "Push Hook"})
    assert handler.await_args[0][0].text == "from commit"  # type: ignore[index]
    assert handler.await_args[0][0].user_id == "uu"  # type: ignore[index]

    assert await c.handle_webhook({**base, "commits": [{}, {}]}, {"x-gitlab-event": "Push Hook"})
    assert handler.await_args[0][0].text == "2 commits pushed to dev"  # type: ignore[index]

    assert await c.handle_webhook(base, {"x-gitlab-event": "Push Hook"})
    assert handler.await_args[0][0].text == "Pushed to dev"  # type: ignore[index]


@pytest.mark.asyncio
async def test_gitlab_issue_event():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "issue",
        "user": {"id": 9},
        "object_attributes": {"title": "Bug", "description": "det", "action": "open", "iid": 3},
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Issue Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Issue open: Bug\ndet"
    assert event.metadata["issue_id"] == 3


@pytest.mark.asyncio
async def test_gitlab_issue_without_title_is_false():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {"object_kind": "issue", "object_attributes": {"action": "open"}, "project": {"id": 1}}
    assert not await c.handle_webhook(body, {"x-gitlab-event": "Issue Hook"})
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_gitlab_merge_request_event():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "merge_request",
        "user": {"id": 3},
        "object_attributes": {
            "title": "MR", "description": "why", "action": "merge", "iid": 8, "source_branch": "feat",
        },
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Merge Request Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "MR merge: MR\nwhy"
    assert event.metadata["mr_iid"] == 8
    assert event.metadata["source_branch"] == "feat"


@pytest.mark.asyncio
async def test_gitlab_merge_request_without_description():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "merge_request_note",
        "user": {},
        "object_attributes": {"title": "T", "state": "opened", "source_branch": "b"},
        "project": {"id": 7},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Merge Request Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "MR opened: T (branch: b)"
    assert event.user_id == "gitlab:"  # no user id, no author id, no project path


@pytest.mark.asyncio
async def test_gitlab_merge_request_without_title():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "merge_request",
        "user": {"id": 3},
        "object_attributes": {"title": "", "action": "open"},
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert not await c.handle_webhook(body, {"x-gitlab-event": "Merge Request Hook"})
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_gitlab_note_event():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "note",
        "user": {"id": 4},
        "object_attributes": {"note": "hello", "noteable_type": "MergeRequest"},
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Note Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "hello"
    assert event.metadata["noteable_type"] == "MergeRequest"


@pytest.mark.asyncio
async def test_gitlab_note_without_text_is_false():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {"object_kind": "note", "object_attributes": {}, "project": {"id": 1}}
    assert not await c.handle_webhook(body, {"x-gitlab-event": "Note Hook"})


@pytest.mark.asyncio
async def test_gitlab_pipeline_event():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    body = {
        "object_kind": "pipeline",
        "user": {"id": 2},
        "object_attributes": {"status": "failed", "ref": "main"},
        "project": {"id": 42, "path_with_namespace": "acme/app"},
    }
    assert await c.handle_webhook(body, {"x-gitlab-event": "Pipeline Hook"})
    event = handler.await_args[0][0]  # type: ignore[index]
    assert event.text == "Pipeline failed for main"
    assert event.metadata["pipeline_status"] == "failed"


@pytest.mark.asyncio
async def test_gitlab_unknown_kind_is_false():
    c, handler = _ready_channel()
    await c.on_message(handler)
    await c.start()
    assert not await c.handle_webhook({"object_kind": "wiki_page", "project": {"id": 1}}, {"x-gitlab-event": "X"})
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_gitlab_send_creates_issue(monkeypatch: pytest.MonkeyPatch):
    c = GitlabChannel()
    await c.start()
    c._token = "tok"
    post = AsyncMock()
    monkeypatch.setattr("raven.channels.gitlab.channel.client_manager.post", post)
    msg = Message(session_id="gitlab:42:7", channel="gitlab", role="assistant", content="note body")
    await c.send("gitlab:42:7", msg)
    url = post.await_args[0][0]  # type: ignore[index]
    assert url.endswith("/api/v4/projects/42/issues")
    assert post.await_args.kwargs["headers"]["PRIVATE-TOKEN"] == "tok"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_gitlab_send_skips_without_project_or_token(monkeypatch: pytest.MonkeyPatch):
    c = GitlabChannel()
    await c.start()
    c._token = ""
    post = AsyncMock()
    monkeypatch.setattr("raven.channels.gitlab.channel.client_manager.post", post)
    msg = Message(session_id="x", channel="gitlab", role="assistant", content="r")
    await c.send("solo", msg)      # no project id in session
    await c.send("gitlab:42:7", msg)  # no token
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_gitlab_send_error_is_swallowed(monkeypatch: pytest.MonkeyPatch):
    c = GitlabChannel()
    await c.start()
    c._token = "tok"
    post = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr("raven.channels.gitlab.channel.client_manager.post", post)
    msg = Message(session_id="gitlab:42:7", channel="gitlab", role="assistant", content="r")
    await c.send("gitlab:42:7", msg)

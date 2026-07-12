from __future__ import annotations

import asyncio

import pytest

from raven.automation.human_approval import ApprovalStatus, HumanApproval, InteractivePrompt


class TestHumanApprovalUpgraded:
    def setup_method(self) -> None:
        self.approval = HumanApproval(default_timeout=0.5)

    def test_interactive_prompt_creation(self) -> None:
        prompt = InteractivePrompt(
            id="p1",
            request_id="r1",
            channel="telegram",
            message="Approve deploy?",
            options={"approve": True, "reject": False},
            timeout=60.0,
        )
        assert prompt.id == "p1"
        assert prompt.request_id == "r1"
        assert prompt.channel == "telegram"
        assert prompt.message == "Approve deploy?"
        assert prompt.options == {"approve": True, "reject": False}
        assert prompt.timeout == 60.0

    def test_interactive_prompt_defaults(self) -> None:
        prompt = InteractivePrompt(
            id="p2",
            request_id="r2",
            channel="web",
            message="test",
        )
        assert prompt.options == {}
        assert prompt.timeout == 3600.0

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_timeout(self) -> None:
        req = await self.approval.request_approval_via_channel(
            "deploy to prod", "slack", timeout=0.2,
        )
        assert req.status == ApprovalStatus.TIMEOUT
        assert req.channel == "slack"

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_auto_approve(self) -> None:
        req = await self.approval.request_approval_via_channel(
            "restart server", "telegram", timeout=0.2, auto_approve=True,
        )
        assert req.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_respond_approve(self) -> None:
        task = asyncio.create_task(
            self.approval.request_approval_via_channel("delete table", "web", timeout=5.0),
        )
        await asyncio.sleep(0.05)
        req_id = list(self.approval._pending.keys())[0]
        success = await self.approval.respond(req_id, approved=True, responded_by="admin", response="OK")
        req = await task
        assert success is True
        assert req.status == ApprovalStatus.APPROVED
        assert req.responded_by == "admin"

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_respond_reject(self) -> None:
        task = asyncio.create_task(
            self.approval.request_approval_via_channel("drop table", "web", timeout=5.0),
        )
        await asyncio.sleep(0.05)
        req_id = list(self.approval._pending.keys())[0]
        success = await self.approval.respond(req_id, approved=False, responded_by="reviewer")
        req = await task
        assert success is True
        assert req.status == ApprovalStatus.REJECTED

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_cancel(self) -> None:
        task = asyncio.create_task(
            self.approval.request_approval_via_channel("restart service", "email", timeout=10.0),
        )
        await asyncio.sleep(0.05)
        req_id = list(self.approval._pending.keys())[0]
        cancelled = await self.approval.cancel(req_id)
        req = await task
        assert cancelled is True
        assert req.status == ApprovalStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_with_context(self) -> None:
        req = await self.approval.request_approval_via_channel(
            "update config", "console",
            context={"env": "staging", "key": "log_level"},
            timeout=0.2,
        )
        assert req.context == {"env": "staging", "key": "log_level"}
        assert req.status == ApprovalStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_invalid_channel_fallback(self) -> None:
        req = await self.approval.request_approval_via_channel(
            "test action", "nonexistent_channel", timeout=0.2,
        )
        assert req.status == ApprovalStatus.TIMEOUT
        assert req.channel == "nonexistent_channel"

    @pytest.mark.asyncio
    async def test_request_approval_via_channel_multiple_concurrent(self) -> None:
        task1 = asyncio.create_task(
            self.approval.request_approval_via_channel("action1", "web", timeout=2.0),
        )
        task2 = asyncio.create_task(
            self.approval.request_approval_via_channel("action2", "web", timeout=2.0),
        )
        await asyncio.sleep(0.05)
        pending = self.approval.get_pending()
        assert len(pending) == 2
        ids = list(self.approval._pending.keys())
        await self.approval.respond(ids[0], approved=True, responded_by="admin")
        await self.approval.respond(ids[1], approved=False, responded_by="admin")
        req1 = await task1
        req2 = await task2
        assert req1.status == ApprovalStatus.APPROVED
        assert req2.status == ApprovalStatus.REJECTED

    @pytest.mark.asyncio
    async def test_original_api_unchanged(self) -> None:
        req = await self.approval.request_approval("legacy action", timeout=0.2)
        assert req.status == ApprovalStatus.TIMEOUT
        assert self.approval.get_pending() == []
        stats = self.approval.get_stats()
        assert stats["total"] >= 1

from __future__ import annotations

import asyncio

import pytest

from raven.automation.human_approval import ApprovalStatus, HumanApproval


class TestHumanApproval:
    def setup_method(self) -> None:
        self.approval = HumanApproval(default_timeout=0.5)

    @pytest.mark.asyncio
    async def test_request_approval_timeout_rejected(self):
        req = await self.approval.request_approval("deploy to prod", timeout=0.2)
        assert req.status == ApprovalStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_request_approval_auto_approve(self):
        req = await self.approval.request_approval("restart server", timeout=0.2, auto_approve=True)
        assert req.status == ApprovalStatus.APPROVED

    @pytest.mark.asyncio
    async def test_respond_approve(self):
        task = asyncio.create_task(self.approval.request_approval("delete table", timeout=5.0))
        await asyncio.sleep(0.05)
        success = await self.approval.respond("", approved=True)
        await task
        assert success is False

    @pytest.mark.asyncio
    async def test_respond_unknown(self):
        success = await self.approval.respond("nonexistent", approved=True)
        assert success is False

    def test_get_pending(self):
        assert self.approval.get_pending() == []

    def test_get_audit(self):
        audit = self.approval.get_audit()
        assert isinstance(audit, list)

    def test_get_stats(self):
        stats = self.approval.get_stats()
        assert stats["pending"] == 0
        assert stats["total"] == 0

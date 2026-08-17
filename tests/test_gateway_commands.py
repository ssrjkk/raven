from __future__ import annotations

from typing import Any

import pytest

from raven.core.auth.models import Permission, Role
from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage
from tests.conftest import MockChannel


@pytest.fixture
def gateway_with_perms(gateway: Gateway) -> Gateway:
    for role in Role:
        for perm in Permission:
            gateway._rbac.add_role_permission(role, perm)
    return gateway


@pytest.fixture
def user() -> dict[str, Any]:
    return {"id": "U1", "name": "Test User", "role": "user"}


def _event(text: str, channel: str = "mock") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id="U1",
        session_id=f"{channel}:C1:default",
        text=text,
        metadata={},
    )


class TestBasicCommands:
    async def test_new_command(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/new"), user)
        assert result is True

    async def test_reset_command(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/reset"), user)
        assert result is True

    async def test_help_command(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/help"), user)
        assert result is True

    async def test_unknown_command(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/nonexistent"), user)
        assert result is not True


class TestMonitorCommands:
    async def test_monitor_list(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor list"), user)
        assert result is True

    async def test_monitor_add(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor add http http://example.com"), user)
        assert result is True

    async def test_monitor_remove(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor remove 1"), user)
        assert result is True

    async def test_monitor_pause(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor pause 1"), user)
        assert result is True

    async def test_monitor_resume(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/monitor resume 1"), user)
        assert result is True


class TestRoutineCommands:
    async def test_routine_list(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine list"), user)
        assert result is True

    async def test_routine_add(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing '0 9 * * *'"), user)
        assert result is True

    async def test_routine_add_unquoted_cron(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(_event("/routine add send_briefing 0 9 * * *"), user)
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines
        assert routines[0].schedule == "0 9 * * *"

    async def test_routine_add_cron_with_name(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        await gateway_with_perms.start()
        result = await gateway_with_perms._handle_command(
            _event("/routine add send_briefing */30 9-18 * * 1-5 brief"), user
        )
        assert result is True
        routines = await gateway_with_perms._routine_store.list_routines(user_id="U1")
        assert routines
        assert routines[0].schedule == "*/30 9-18 * * 1-5"
        assert routines[0].name == "brief"


class TestTaskCommands:
    async def test_task_command_routes(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/task do something"), user)
        assert result is True

    async def test_task_list(self, gateway: Gateway, user: dict[str, Any]):
        await gateway.start()
        result = await gateway._handle_command(_event("/task list"), user)
        assert result is True


class TestCodeCommands:
    async def test_code_index(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code index"), user)
        assert result is True

    async def test_code_search(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code search test"), user)
        assert result is True

    async def test_code_review(self, gateway_with_perms: Gateway, user: dict[str, Any]):
        result = await gateway_with_perms._handle_command(_event("/code review test.py"), user)
        assert result is True


class TestVoiceCommands:
    async def test_voice_tts(self, gateway: Gateway, user: dict[str, Any]):
        result = await gateway._handle_command(_event("/voice tts hello"), user)
        assert result is True


class TestCleanText:
    async def test_clean_text_strips_mention(self, gateway: Gateway):
        result = gateway._clean_text("discord", "<@12345> hello")
        assert "hello" in result

    async def test_clean_text_no_mention(self, gateway: Gateway):
        result = gateway._clean_text("telegram", "hello world")
        assert result == "hello world"

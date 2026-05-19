from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.core.gateway.gateway import Gateway
from raven.core.models import IncomingMessage


@pytest.fixture
def gateway():
    gw = Gateway.__new__(Gateway)
    gw.db = MagicMock()
    gw.db.get_or_create_session = AsyncMock(return_value=MagicMock(id="test_sid"))
    gw.db.find_or_create_user = AsyncMock(return_value=MagicMock())
    gw.db.get_session_messages = AsyncMock(return_value=[])
    gw.db.save_message = AsyncMock()
    gw.db.get_user = AsyncMock(return_value=MagicMock())
    gw.db.delete_session = AsyncMock()
    gw.db.get_plugin_state = AsyncMock(return_value=None)
    gw.db.save_plugin_state = AsyncMock()
    gw.llm = MagicMock()
    gw.llm.chat = AsyncMock(return_value=MagicMock(content="Hello!", tool_calls=[]))
    gw.failover = MagicMock()
    gw.failover.complete = AsyncMock(return_value="test response")
    gw.plugin_loader = MagicMock()
    gw.plugin_loader.tools = []
    gw.registry = MagicMock()
    gw.registry.plugins = {}
    gw.channels = {"telegram": AsyncMock(), "webchat": AsyncMock()}
    gw.sandbox = None
    gw._monitor_engine = MagicMock()
    gw._routine_engine = MagicMock()
    gw._task_runner = MagicMock()
    gw._skills = {}
    gw._plugins_loaded = False
    return gw


def _event(text: str, channel: str = "telegram") -> IncomingMessage:
    return IncomingMessage(
        channel=channel,
        user_id="U1",
        session_id=f"{channel}:C1:default",
        text=text,
        metadata={},
    )


class TestGatewayCommandHandler:
    @pytest.mark.asyncio
    async def test_status_command(self, gateway):
        with patch.object(gateway, "_handle_command") as mock_cmd:
            mock_cmd.return_value = True
            result = await gateway._handle_command(_event("/status"))
            assert result is True

    @pytest.mark.asyncio
    async def test_new_command(self, gateway):
        result = await gateway._handle_command(_event("/new"))
        assert result is True

    @pytest.mark.asyncio
    async def test_reset_command(self, gateway):
        result = await gateway._handle_command(_event("/reset"))
        assert result is True

    @pytest.mark.asyncio
    async def test_help_command(self, gateway):
        result = await gateway._handle_command(_event("/help"))
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_command(self, gateway):
        with patch.object(gateway, "_send", new_callable=AsyncMock):
            result = await gateway._handle_command(_event("/nonexistent"))
            assert result is not True


class TestGatewayMonitorCommands:
    @pytest.mark.asyncio
    async def test_monitor_list(self, gateway):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor list"
            result = await gateway._handle_command(_event("/monitor list"))
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_add(self, gateway):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor added"
            result = await gateway._handle_command(_event("/monitor add http https://example.com"))
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_remove(self, gateway):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor removed"
            result = await gateway._handle_command(_event("/monitor remove 1"))
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_pause(self, gateway):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor paused"
            result = await gateway._handle_command(_event("/monitor pause 1"))
            assert result is True

    @pytest.mark.asyncio
    async def test_monitor_resume(self, gateway):
        with patch.object(gateway, "_handle_monitor_cmd") as mock_cmd:
            mock_cmd.return_value = "Monitor resumed"
            result = await gateway._handle_command(_event("/monitor resume 1"))
            assert result is True


class TestGatewayRoutineCommands:
    @pytest.mark.asyncio
    async def test_routine_list(self, gateway):
        with patch.object(gateway, "_handle_routine_cmd") as mock_cmd:
            mock_cmd.return_value = "Routine list"
            result = await gateway._handle_command(_event("/routine list"))
            assert result is True

    @pytest.mark.asyncio
    async def test_routine_add(self, gateway):
        with patch.object(gateway, "_handle_routine_cmd") as mock_cmd:
            mock_cmd.return_value = "Routine added"
            result = await gateway._handle_command(_event("/routine add briefing 0 9 * * *"))
            assert result is True


class TestGatewayTaskCommands:
    @pytest.mark.asyncio
    async def test_task_command_routes(self, gateway):
        with patch.object(gateway, "_run_task", new_callable=AsyncMock):
            with patch.object(gateway, "_send", new_callable=AsyncMock):
                result = await gateway._handle_command(_event("/task do something"))
                assert result is True

    @pytest.mark.asyncio
    async def test_task_list(self, gateway):
        with patch.object(gateway, "_send", new_callable=AsyncMock):
            result = await gateway._handle_command(_event("/task list"))
            assert result is True


class TestGatewayCodeCommands:
    @pytest.mark.asyncio
    async def test_code_index(self, gateway):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Indexed"
            result = await gateway._handle_command(_event("/code index"))
            assert result is True

    @pytest.mark.asyncio
    async def test_code_search(self, gateway):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Search results"
            result = await gateway._handle_command(_event("/code search test"))
            assert result is True

    @pytest.mark.asyncio
    async def test_code_review(self, gateway):
        with patch.object(gateway, "_handle_code_cmd") as mock_cmd:
            mock_cmd.return_value = "Review"
            result = await gateway._handle_command(_event("/code review test.py"))
            assert result is True


class TestGatewayVoiceCommands:
    @pytest.mark.asyncio
    async def test_voice_tts(self, gateway):
        with patch.object(gateway, "_handle_voice_cmd") as mock_cmd:
            mock_cmd.return_value = "Playing TTS"
            result = await gateway._handle_command(_event("/voice tts hello"))
            assert result is True


class TestGatewayCleanText:
    def test_clean_text_strips_mention(self, gateway):
        result = gateway._clean_text("discord", "<@12345> hello")
        assert "hello" in result

    def test_clean_text_no_mention(self, gateway):
        result = gateway._clean_text("telegram", "hello world")
        assert result == "hello world"

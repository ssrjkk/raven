from __future__ import annotations

import contextlib
import inspect
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from raven.core.plugin_loader import PluginLoader, func_to_tool


def _collect_tools(module):
    tools = {}
    for name, obj in inspect.getmembers(module, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        tool = func_to_tool(obj)
        tools[name] = tool
    return tools


_CRON_SKIP = False
try:
    import apscheduler
except ImportError:
    _CRON_SKIP = True

cron_skip = pytest.mark.skipif(_CRON_SKIP, reason="apscheduler not installed")


class TestPluginConstants:
    def test_cron_constants(self):
        if _CRON_SKIP:
            pytest.skip("apscheduler not installed")
        from raven.plugins.cron import plugin as p

        assert p.PLUGIN_NAME == "cron"

    def test_files_constants(self):
        from raven.plugins.files import plugin as p

        assert p.PLUGIN_NAME == "files"

    def test_api_constants(self):
        from raven.plugins.api import plugin as p

        assert p.PLUGIN_NAME == "api"

    def test_git_constants(self):
        from raven.plugins.git import plugin as p

        assert p.PLUGIN_NAME == "git"

    def test_memory_constants(self):
        from raven.plugins.memory import plugin as p

        assert p.PLUGIN_NAME == "memory"

    def test_ocr_constants(self):
        from raven.plugins.ocr import plugin as p

        assert p.PLUGIN_NAME == "ocr"

    def test_process_constants(self):
        from raven.plugins.process import plugin as p

        assert p.PLUGIN_NAME == "process"

    def test_sessions_constants(self):
        from raven.plugins.sessions import plugin as p

        assert p.PLUGIN_NAME == "sessions"


@cron_skip
class TestCronPlugin:
    @pytest.mark.asyncio
    async def test_schedule(self):
        from raven.plugins.cron import plugin as p

        result = await p.schedule("* * * * *", "test task", task_id="test_cron")
        assert "Scheduled" in result
        assert "test_cron" in result

    @pytest.mark.asyncio
    async def test_list_schedules(self):
        from raven.plugins.cron import plugin as p

        result = await p.list_schedules()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_cancel_schedule(self):
        from raven.plugins.cron import plugin as p

        await p.schedule("* * * * *", "cancel_test", task_id="cancel_test")
        result = await p.cancel_schedule("cancel_test")
        assert "Cancelled" in result

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self):
        from raven.plugins.cron import plugin as p

        result = await p.cancel_schedule("nonexistent")
        assert "Failed" in result

    def test_tool_discovery(self):
        from raven.plugins.cron import plugin as p

        tools = _collect_tools(p)
        assert "schedule" in tools
        assert "list_schedules" in tools
        assert "cancel_schedule" in tools
        for t in tools.values():
            assert t.description
            assert t.handler


class TestFilesPlugin:
    _PATCH_ROOTS = ()

    def _allow(self, tmp_path):
        from pathlib import Path

        from raven.plugins.files import plugin as p

        return patch.object(
            p,
            "ALLOWED_ROOTS",
            [
                str(Path.home()),
                str(Path.cwd()),
                "/tmp",
                str(tmp_path.resolve()),
            ],
        )

    @pytest.mark.asyncio
    async def test_write_and_read(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            test_file = tmp_path / "test.txt"
            write_result = await p.write(str(test_file), "hello world")
            assert write_result
            content = await p.read(str(test_file))
            assert "hello world" in content

    @pytest.mark.asyncio
    async def test_append(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            test_file = tmp_path / "append.txt"
            await p.write(str(test_file), "line1")
            await p.append(str(test_file), "line2")
            content = await p.read(str(test_file))
            assert "line1" in content
            assert "line2" in content

    @pytest.mark.asyncio
    async def test_ls(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            (tmp_path / "a.txt").write_text("a")
            (tmp_path / "b.txt").write_text("b")
            result = await p.ls(str(tmp_path))
            assert "a.txt" in result
            assert "b.txt" in result

    @pytest.mark.asyncio
    async def test_glob(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            (tmp_path / "foo.py").write_text("x")
            result = await p.glob("*.py", str(tmp_path))
            assert "foo.py" in result

    @pytest.mark.asyncio
    async def test_info(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            test_file = tmp_path / "info.txt"
            test_file.write_text("test")
            result = await p.info(str(test_file))
            assert "info.txt" in result

    @pytest.mark.asyncio
    async def test_read_limit(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            test_file = tmp_path / "long.txt"
            test_file.write_text("a" * 1000)
            content = await p.read(str(test_file), limit=10)
            assert "truncated" in content

    @pytest.mark.asyncio
    async def test_path_denied(self):
        from raven.plugins.files import plugin as p

        with pytest.raises(PermissionError):
            await p.read("/etc/shadow")

    @pytest.mark.asyncio
    async def test_ls_empty_dir(self, tmp_path):
        from raven.plugins.files import plugin as p

        with self._allow(tmp_path):
            empty = tmp_path / "empty"
            empty.mkdir()
            result = await p.ls(str(empty))
            assert isinstance(result, str)

    def test_tool_discovery(self):
        from raven.plugins.files import plugin as p

        tools = _collect_tools(p)
        for name in ("read", "write", "append", "ls", "glob", "info"):
            assert name in tools


class TestApiPlugin:
    @pytest.mark.asyncio
    async def test_http_get_success(self):
        from raven.plugins.api import plugin as p

        response = httpx.Response(200, json={"ok": True})
        with (
            patch("raven.plugins.api.plugin.validate_url", return_value=None),
            patch(
                "raven.plugins.api.plugin.safe_fetch_async",
                new=AsyncMock(return_value=response),
            ) as mock_fetch,
        ):
            result = await p.http_get("https://example.com")
        assert "200" in result
        mock_fetch.assert_awaited_once_with("https://example.com", method="GET", timeout=30)

    @pytest.mark.asyncio
    async def test_http_get_timeout(self):
        from raven.plugins.api import plugin as p

        with (
            patch("raven.plugins.api.plugin.validate_url", return_value=None),
            patch(
                "raven.plugins.api.plugin.safe_fetch_async",
                new=AsyncMock(side_effect=TimeoutError("timeout")),
            ),
        ):
            result = await p.http_get("https://example.com", timeout=1)
        assert "Error" in result or "error" in result

    @pytest.mark.asyncio
    async def test_validate_url_blocks_localhost(self):
        from raven.plugins.api import plugin as p

        result = await p.http_get("http://localhost:8080")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_validate_url_blocks_private_ip(self):
        from raven.plugins.api import plugin as p

        result = await p.http_get("http://127.0.0.1")
        assert "blocked" in result.lower() or "Error" in result

    @pytest.mark.asyncio
    async def test_http_post(self):
        from raven.plugins.api import plugin as p

        response = httpx.Response(201, json={"id": 1})
        with (
            patch("raven.plugins.api.plugin.validate_url", return_value=None),
            patch(
                "raven.plugins.api.plugin.safe_fetch_async",
                new=AsyncMock(return_value=response),
            ) as mock_fetch,
        ):
            result = await p.http_post(
                "https://example.com/api", data='{"name": "test"}'
            )
        assert "201" in result
        mock_fetch.assert_awaited_once_with(
            "https://example.com/api",
            method="POST",
            json={"name": "test"},
            timeout=30,
        )

    def test_tool_discovery(self):
        from raven.plugins.api import plugin as p

        tools = _collect_tools(p)
        for name in ("http_get", "http_post", "http_put", "http_delete"):
            assert name in tools


class TestGitPlugin:
    @pytest.mark.asyncio
    async def test_git_status_no_repo(self, tmp_path):
        from raven.plugins.git import plugin as p

        result = await p.git_status(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_git_log_no_repo(self, tmp_path):
        from raven.plugins.git import plugin as p

        result = await p.git_log(str(tmp_path), count=5)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_git_branch_no_repo(self, tmp_path):
        from raven.plugins.git import plugin as p

        result = await p.git_branch(str(tmp_path))
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_git_diff_no_repo(self, tmp_path):
        from raven.plugins.git import plugin as p

        result = await p.git_diff(str(tmp_path))
        assert isinstance(result, str)

    def test_tool_discovery(self):
        from raven.plugins.git import plugin as p

        tools = _collect_tools(p)
        for name in ("git_status", "git_log", "git_diff", "git_commit", "git_branch", "git_push", "git_pull"):
            assert name in tools


class TestMemoryPlugin:
    @pytest.mark.asyncio
    async def test_remember_and_recall(self):
        from raven.plugins.memory import plugin as p

        store_result = await p.remember("test_key", "test_value")
        assert "test_key" in store_result
        value = await p.recall("test_key")
        assert "test_value" in value

    @pytest.mark.asyncio
    async def test_forget(self):
        from raven.plugins.memory import plugin as p

        await p.remember("forget_key", "forget_val")
        result = await p.forget("forget_key")
        assert "forget_key" in result

    @pytest.mark.asyncio
    async def test_recall_missing(self):
        from raven.plugins.memory import plugin as p

        value = await p.recall("nonexistent_key")
        assert "nothing found" in value.lower()

    @pytest.mark.asyncio
    async def test_list_keys(self):
        from raven.plugins.memory import plugin as p

        await p.remember("list_key_1", "val1")
        result = await p.list_keys()
        assert "list_key_1" in result

    @pytest.mark.asyncio
    async def test_store_and_retrieve_knowledge(self):
        from raven.plugins.memory import plugin as p

        await p.store_knowledge("python", "Python is a programming language")
        result = await p.retrieve_knowledge("python")
        assert "Python" in result

    def test_tool_discovery(self):
        from raven.plugins.memory import plugin as p

        tools = _collect_tools(p)
        for name in (
            "remember",
            "recall",
            "forget",
            "search_memory",
            "list_keys",
            "store_knowledge",
            "retrieve_knowledge",
        ):
            assert name in tools


class TestOcrPlugin:
    @pytest.mark.asyncio
    async def test_ocr_image_no_tesseract(self, tmp_path):
        from raven.plugins.ocr import plugin as p

        test_img = tmp_path / "test.png"
        test_img.write_text("fake image")
        result = await p.ocr_image(str(test_img))
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_ocr_image_missing(self):
        from raven.plugins.ocr import plugin as p

        result = await p.ocr_image("/nonexistent/image.png")
        assert "Tesseract" in result or "Error" in result

    def test_tool_discovery(self):
        from raven.plugins.ocr import plugin as p

        tools = _collect_tools(p)
        assert "ocr_image" in tools
        assert "ocr_url" in tools


class TestProcessPlugin:
    @pytest.mark.asyncio
    async def test_run_echo(self):
        from raven.plugins.process import plugin as p

        result = await p.run("whoami")
        assert result.strip()
        assert "Error" not in result

    @pytest.mark.asyncio
    async def test_run_rejects_shell_escape(self):
        from raven.plugins.process import plugin as p

        cmd = "cmd.exe /c echo pwned" if sys.platform == "win32" else "bash -c 'echo pwned'"
        result = await p.run(cmd)
        assert "not in the allowed commands" in result

    @pytest.mark.asyncio
    async def test_run_rejects_env_dump(self):
        from raven.plugins.process import plugin as p

        cmd = "set" if sys.platform == "win32" else "env"
        result = await p.run(cmd)
        assert "not in the allowed commands" in result

    @pytest.mark.asyncio
    async def test_kill_refuses_self(self):
        import os

        from raven.plugins.process import plugin as p

        result = await p.kill(os.getpid())
        assert "refusing to kill" in result

    @pytest.mark.asyncio
    async def test_run_python(self):
        from raven.plugins.process import plugin as p

        result = await p.run_python("print('hi')")
        assert "hi" in result

    @pytest.mark.asyncio
    async def test_list_processes(self):
        from raven.plugins.process import plugin as p

        result = await p.list_processes()
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_run_timeout(self):
        from raven.plugins.process import plugin as p

        cmd = "ping -n 60 127.0.0.1" if sys.platform == "win32" else "sleep 10"
        result = await p.run(cmd, timeout=1)
        assert isinstance(result, str)

    def test_tool_discovery(self):
        from raven.plugins.process import plugin as p

        tools = _collect_tools(p)
        for name in ("run", "run_python", "list_processes", "kill"):
            assert name in tools


class TestSessionsPlugin:
    @pytest.mark.asyncio
    async def test_sessions_list_uninitialized(self):
        from raven.plugins.sessions import plugin as p

        result = await p.sessions_list()
        assert "not initialized" in result.lower()

    @pytest.mark.asyncio
    async def test_sessions_history_no_session(self):
        from raven.plugins.sessions import plugin as p

        result = await p.sessions_history()
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_sessions_send_uninitialized(self):
        from raven.plugins.sessions import plugin as p

        result = await p.sessions_send("test_session")
        assert "Database" in result

    @pytest.mark.asyncio
    async def test_sessions_spawn_uninitialized(self):
        from raven.plugins.sessions import plugin as p

        result = await p.sessions_spawn(task="test task")
        assert "Database" in result

    @pytest.mark.asyncio
    async def test_sessions_history_with_session(self):
        from raven.plugins.sessions import plugin as p

        mock_db = MagicMock()
        mock_db.get_session_messages = AsyncMock(return_value=[])
        p._db = mock_db
        result = await p.sessions_history(session_id="test_sid")
        assert "No messages" in result
        p._db = None

    def test_tool_discovery(self):
        from raven.plugins.sessions import plugin as p

        tools = _collect_tools(p)
        for name in ("sessions_list", "sessions_history", "sessions_send", "sessions_spawn"):
            assert name in tools


class TestPluginLoader:
    def test_load_api_plugins(self):
        loader = PluginLoader()
        from pathlib import Path

        plugins_dir = Path(__file__).parent.parent / "raven" / "plugins"
        for pdir in plugins_dir.iterdir():
            if pdir.is_dir() and pdir.name not in ("__pycache__", "cron"):
                with contextlib.suppress(Exception):
                    loader.load_from_dir(pdir)
        tool_names = [t.name for t in loader.tools]
        assert len(tool_names) >= 25

    def test_to_openai_tools(self):
        loader = PluginLoader()
        from pathlib import Path

        plugins_dir = Path(__file__).parent.parent / "raven" / "plugins"
        for pdir in plugins_dir.iterdir():
            if pdir.is_dir() and pdir.name not in ("__pycache__", "cron"):
                with contextlib.suppress(Exception):
                    loader.load_from_dir(pdir)
        openai_tools = loader.to_openai_tools()
        assert len(openai_tools) >= 25
        assert all(t["type"] == "function" for t in openai_tools)

    def test_func_to_tool_creates_valid_tool(self):
        async def sample_tool(name: str, count: int = 1) -> str:
            """A sample tool. Args: name (str): The name, count (int): The count"""
            return f"{name} x{count}"

        tool = func_to_tool(sample_tool)
        assert tool.name == "sample_tool"
        assert "name" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["name"]

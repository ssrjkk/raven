from __future__ import annotations

import pytest

from raven.core.sandbox import Sandbox, SandboxConfig


@pytest.mark.asyncio
async def test_sandbox_direct_mode():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print('hello')")
    assert result == "print('hello')"


@pytest.mark.asyncio
async def test_sandbox_denied_tool():
    s = Sandbox(SandboxConfig(mode="none", denied_tools=["exec"]))
    result = await s.exec("code", tool_name="exec")
    assert "denied" in result


@pytest.mark.asyncio
async def test_sandbox_allowed_tool():
    s = Sandbox(SandboxConfig(mode="none", allowed_tools=["read"]))
    result = await s.exec("code", tool_name="write")
    assert "not allowed" in result


@pytest.mark.asyncio
async def test_sandbox_subprocess_simple():
    s = Sandbox(SandboxConfig(mode="subprocess"))
    result = await s.exec("print('hello from sandbox')")
    assert "hello from sandbox" in result


@pytest.mark.asyncio
async def test_sandbox_subprocess_stderr():
    s = Sandbox(SandboxConfig(mode="subprocess"))
    result = await s.exec("import sys; print('out'); sys.stderr.write('err')")
    assert "out" in result
    assert "err" in result


@pytest.mark.asyncio
async def test_sandbox_subprocess_timeout():
    s = Sandbox(SandboxConfig(mode="subprocess", timeout=1))
    result = await s.exec("import time; time.sleep(10)")
    assert "timed out" in result


@pytest.mark.asyncio
async def test_sandbox_subprocess_no_network():
    s = Sandbox(SandboxConfig(mode="subprocess", allow_network=False))
    result = await s.exec("print('ok')")
    assert "ok" in result


@pytest.mark.asyncio
async def test_sandbox_docker_no_docker_package():
    s = Sandbox(SandboxConfig(mode="docker"))
    result = await s.exec("print('hi')")
    assert "docker" in result.lower() or "not available" in result


@pytest.mark.asyncio
async def test_sandbox_unknown_mode():
    s = Sandbox(SandboxConfig(mode="jail"))
    result = await s.exec("code")
    assert "unknown" in result.lower()


@pytest.mark.asyncio
async def test_sandbox_cleanup():
    s = Sandbox(SandboxConfig(mode="subprocess"))
    await s.exec("print('test')")
    assert s._tmpdir is not None
    await s.cleanup()
    assert s._tmpdir is None


@pytest.mark.asyncio
async def test_sandbox_default_config():
    s = Sandbox()
    assert s.config.mode == "none"
    assert s.config.denied_tools == []

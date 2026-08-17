from __future__ import annotations

import sys

import pytest

from raven.core.sandbox import Sandbox, SandboxConfig


def _block_docker_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "docker", None)


@pytest.mark.asyncio
async def test_sandbox_direct_mode():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print('hello')")
    assert "hello" in result


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
    result = await s.exec("print('out'); raise ValueError('boom')")
    assert "out" in result
    assert "boom" in result


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
async def test_sandbox_docker_no_docker_package(monkeypatch: pytest.MonkeyPatch):
    _block_docker_import(monkeypatch)
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
    assert len(s._tmpdirs) > 0
    await s.cleanup()
    assert len(s._tmpdirs) == 0


@pytest.mark.asyncio
async def test_sandbox_default_config():
    s = Sandbox()
    assert s.config.mode == "subprocess"
    assert s.config.denied_tools == []


@pytest.mark.asyncio
async def test_sandbox_direct_blocks_dunder_attr():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print(''.__class__)")
    assert "[denied]" in result


@pytest.mark.asyncio
async def test_sandbox_direct_blocks_subclasses_chain():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print(().__class__.__bases__[0].__subclasses__())")
    assert "[denied]" in result


@pytest.mark.asyncio
async def test_sandbox_direct_blocks_dict_descriptor():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print(object.__dict__['__subclasses__'])")
    assert "[denied]" in result


@pytest.mark.asyncio
async def test_sandbox_direct_blocks_format_bypass():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print('{0.__class__}'.format(()))")
    assert "[denied]" in result


@pytest.mark.asyncio
async def test_sandbox_direct_blocks_vars():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("print(vars(object))")
    assert "[denied]" in result


@pytest.mark.asyncio
async def test_sandbox_direct_allows_legit_introspection():
    s = Sandbox(SandboxConfig(mode="none"))
    result = await s.exec("x = [1, 2, 3]; print(len(x))")
    assert "3" in result


class TestNetworkRules:
    def test_effective_network_rules_default_deny(self):
        cfg = SandboxConfig(mode="subprocess", allow_network=False)
        rules = cfg.effective_network_rules
        assert rules["allow"] == []
        assert rules["deny"] == ["*"]

    def test_effective_network_rules_default_allow(self):
        cfg = SandboxConfig(mode="subprocess", allow_network=True)
        rules = cfg.effective_network_rules
        assert rules["allow"] == ["*"]

    def test_effective_network_rules_custom(self):
        cfg = SandboxConfig(mode="docker", allow_network=True, network_rules={"allow": ["pypi.org"]})
        rules = cfg.effective_network_rules
        assert rules["allow"] == ["pypi.org"]

    def test_build_net_entrypoint_full_deny(self):
        cfg = SandboxConfig(mode="docker", allow_network=False)
        s = Sandbox(cfg)
        assert s._build_net_allow_entrypoint() is None

    def test_build_net_entrypoint_selective_allow(self):
        cfg = SandboxConfig(mode="docker", allow_network=True, network_rules={"allow": ["pypi.org"], "deny": ["*"]})
        s = Sandbox(cfg)
        ep = s._build_net_allow_entrypoint()
        assert ep is not None
        assert "iptables" in ep
        assert "iptables -A OUTPUT -d pypi.org -j ACCEPT" in ep

    def test_build_net_entrypoint_wildcard_allow(self):
        cfg = SandboxConfig(mode="docker", allow_network=True, network_rules={"allow": ["*"]})
        s = Sandbox(cfg)
        assert s._build_net_allow_entrypoint() is None

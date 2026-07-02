from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_svc = Path(__file__).parent.parent.parent / "services" / "code-service"
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

agent_mod = importlib.import_module("agent")
AgentMode = agent_mod.AgentMode
RavenCodeAgent = agent_mod.RavenCodeAgent


class TestAgentMode:
    def test_build_enum(self):
        assert AgentMode.BUILD.value == "build"

    def test_plan_enum(self):
        assert AgentMode.PLAN.value == "plan"

    def test_general_enum(self):
        assert AgentMode.GENERAL.value == "general"


class TestRavenCodeAgent:
    @pytest.mark.asyncio
    async def test_agent_init_build(self):
        agent = RavenCodeAgent(mode=AgentMode.BUILD, workspace=".")
        assert agent.mode == AgentMode.BUILD
        assert agent.workspace is not None

    @pytest.mark.asyncio
    async def test_agent_init_plan(self):
        agent = RavenCodeAgent(mode=AgentMode.PLAN, workspace=".")
        assert agent.mode == AgentMode.PLAN

    @pytest.mark.asyncio
    async def test_agent_init_general(self):
        agent = RavenCodeAgent(mode=AgentMode.GENERAL, workspace=".")
        assert agent.mode == AgentMode.GENERAL

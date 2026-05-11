from __future__ import annotations
from typing import Any
from loguru import logger
from raven.core.db import Database
from raven.core.llm import LLMRouter
from raven.core.agent.agent import Agent, AgentConfig, DEFAULT_SYSTEM_PROMPT
from raven.core.models import Session, PluginTool
from raven.core.config import settings


class AgentRegistry:
    def __init__(self, db: Database, llm: LLMRouter, tools: list[PluginTool]):
        self.db = db
        self.llm = llm
        self.tools = tools
        self._configs: dict[str, AgentConfig] = {}
        self._channel_agents: dict[str, str] = {}
        self._default_config = AgentConfig()

    def register_agent(self, agent_id: str, config: AgentConfig):
        self._configs[agent_id] = config
        logger.info("Registered agent: {}", agent_id)

    def map_channel(self, channel: str, agent_id: str):
        self._channel_agents[channel] = agent_id
        logger.info("Mapped channel {} → agent {}", channel, agent_id)

    def get_config(self, agent_id: str) -> AgentConfig:
        return self._configs.get(agent_id) or self._default_config

    def get_agent_for_channel(self, channel: str) -> str:
        return self._channel_agents.get(channel, "default")

    def create_agent(self, session: Session, agent_id: str | None = None) -> Agent:
        aid = agent_id or self._channel_agents.get(session.channel, "default")
        config = self.get_config(aid)
        return Agent(
            session=session,
            tools=self.tools,
            db=self.db,
            llm=self.llm,
            config=config,
        )

    def setup_defaults(self):
        ws = settings.workspace_path if hasattr(settings, "workspace_path") else None
        default = AgentConfig(
            agent_id="default",
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            use_memory=True,
            workspace=ws,
        )
        self.register_agent("default", default)

        assistant = AgentConfig(
            agent_id="assistant",
            system_prompt=(
                "You are Raven, a helpful AI assistant. You are concise and accurate.\n"
                "Use tools when needed to answer questions. Provide clear, well-structured responses."
            ),
            use_memory=True,
            workspace=ws,
        )
        self.register_agent("assistant", assistant)

        coder = AgentConfig(
            agent_id="coder",
            system_prompt=(
                "You are Raven, an expert programming assistant.\n"
                "Write clean, well-documented code. Explain your reasoning.\n"
                "You can execute Python code to verify solutions."
            ),
            model=None,
            use_memory=True,
            workspace=ws,
        )
        self.register_agent("coder", coder)

        self.map_channel("telegram", "default")
        self.map_channel("discord", "default")
        self.map_channel("webchat", "assistant")
        self.map_channel("slack", "default")
        self.map_channel("whatsapp", "default")
        self.map_channel("matrix", "default")
        self.map_channel("webhook", "assistant")

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {
                "id": aid,
                "system_prompt": cfg.system_prompt[:100] if cfg.system_prompt else "default",
                "model": cfg.model,
                "use_memory": cfg.use_memory,
            }
            for aid, cfg in self._configs.items()
        ]

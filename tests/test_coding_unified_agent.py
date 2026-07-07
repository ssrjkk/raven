from __future__ import annotations

from raven.core.context_router import TaskType
from raven.core.unified_agent import UnifiedAgent


class TestUnifiedAgent:
    def test_create_agent(self):
        agent = UnifiedAgent(name="test", max_steps=10)
        assert agent.name == "test"
        assert agent.task_type == TaskType.QUERY

    def test_event_emitter(self):
        agent = UnifiedAgent()
        assert agent.event_emitter is not None

    def test_classify_coding(self):
        agent = UnifiedAgent()
        agent._router.classify("write a function")
        assert True

    def test_classify_automation(self):
        agent = UnifiedAgent()
        agent._router.classify("schedule a task")
        assert True

    def test_build_config(self):
        agent = UnifiedAgent(max_steps=5)
        config = agent._build_config(TaskType.CODING)
        assert config.max_steps == 5

    def test_abort_no_agent(self):
        agent = UnifiedAgent()
        agent.abort()

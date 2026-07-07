from __future__ import annotations

from raven.core.context_router import ContextRouter, TaskType


class TestContextRouter:
    def setup_method(self) -> None:
        self.router = ContextRouter()

    def test_classify_coding_write(self):
        assert self.router.classify("write a function to calculate fibonacci") == TaskType.CODING

    def test_classify_coding_refactor(self):
        assert self.router.classify("refactor the main module and add tests") == TaskType.CODING

    def test_classify_coding_install(self):
        assert self.router.classify("install numpy and pandas") == TaskType.CODING

    def test_classify_coding_read(self):
        assert self.router.classify("read the file and show me the contents") == TaskType.CODING

    def test_classify_automation_schedule(self):
        assert self.router.classify("schedule a backup every day at midnight") == TaskType.AUTOMATION

    def test_classify_automation_monitor(self):
        assert self.router.classify("monitor the server and alert if CPU > 90%") == TaskType.AUTOMATION

    def test_classify_automation_deploy(self):
        assert self.router.classify("deploy the latest version to production") == TaskType.AUTOMATION

    def test_classify_hybrid(self):
        assert self.router.classify("write a backup script and schedule it with cron") == TaskType.HYBRID

    def test_classify_query(self):
        assert self.router.classify("what is the capital of France?") == TaskType.QUERY

    def test_classify_empty(self):
        assert self.router.classify("") == TaskType.QUERY

    def test_confidence_coding(self):
        task_type, confidence = self.router.classify_with_confidence("write a function")
        assert task_type == TaskType.CODING
        assert confidence > 0

    def test_confidence_automation(self):
        task_type, confidence = self.router.classify_with_confidence("schedule every hour")
        assert task_type == TaskType.AUTOMATION
        assert confidence > 0

    def test_confidence_query(self):
        task_type, confidence = self.router.classify_with_confidence("hello")
        assert task_type == TaskType.QUERY
        assert confidence == 0.3

    def test_system_prompt_coding(self):
        prompt = self.router.get_system_prompt_modifier("write a test for this module")
        assert "code" in prompt.lower()

    def test_system_prompt_automation(self):
        prompt = self.router.get_system_prompt_modifier("schedule a nightly backup")
        assert "automation" in prompt.lower()

    def test_system_prompt_hybrid(self):
        prompt = self.router.get_system_prompt_modifier("write a script and schedule it")
        assert prompt != ""

    def test_system_prompt_low_confidence(self):
        prompt = self.router.get_system_prompt_modifier("hello world")
        assert prompt == ""

from __future__ import annotations

from raven.core.context_router import ContextRouter, TaskType

_LABELED_TESTS: list[tuple[str, str]] = [
    # coding
    ("write a function to calculate fibonacci", "coding"),
    ("implement a REST API endpoint", "coding"),
    ("fix the bug in parse_cron method", "coding"),
    ("refactor the database module", "coding"),
    ("add unit tests for the scheduler", "coding"),
    ("install pandas and numpy", "coding"),
    ("create a pull request for this branch", "coding"),
    ("optimize the query for better performance", "coding"),
    ("merge the feature branch into main", "coding"),
    ("create a dashboard for system metrics", "coding"),
    ("add error handling function to the API client", "coding"),
    ("refactor the error handling in the http client", "coding"),
    ("fix the null pointer exception in the data module", "coding"),
    ("write unit tests for the auth module", "coding"),
    ("implement a sorting algorithm", "coding"),
    ("delete the obsolete test fixture file", "coding"),
    ("compile the rust project for production", "coding"),
    ("run lint on all python source files", "coding"),
    # automation
    ("schedule this script to run every day at 9am", "automation"),
    ("send a notification when the build fails", "automation"),
    ("deploy the latest version to production", "automation"),
    ("monitor the API for downtime", "automation"),
    ("set up a webhook for github events", "automation"),
    ("backup the database every 6 hours", "automation"),
    ("configure alerting for high CPU usage", "automation"),
    ("set up a cron job to clean up temp files", "automation"),
    ("set up CI/CD pipeline with github actions", "automation"),
    ("create a workflow that deploys after tests pass", "automation"),
    ("write a python script that monitors disk usage and sends alerts when space is low", "hybrid"),
    ("schedule a weekly report generation", "automation"),
    ("notify the team when deployment completes", "automation"),
    ("trigger an alert on high memory usage", "automation"),
    # hybrid
    ("write a script and schedule it with cron", "hybrid"),
    ("fix the bug and deploy to production", "hybrid"),
    ("create a test suite and run it on every push", "hybrid"),
    ("write migration script and schedule it monthly", "hybrid"),
    ("patch the vulnerability and deploy to production", "hybrid"),
    ("test the api endpoint and deploy if checks pass", "hybrid"),
    # query
    ("what is the capital of France?", "query"),
    ("explain how quantum computing works", "query"),
    ("what's the weather like today?", "query"),
    ("what is the meaning of life", "query"),
    ("tell me a fun fact about space", "query"),
    ("how do neural networks work", "query"),
    ("list all countries in europe", "query"),
    ("what time is it in tokyo", "query"),
    ("hello", "query"),
    ("tell me a joke", "query"),
]


class TestMetricsClassificationAccuracy:
    def setup_method(self) -> None:
        self.router = ContextRouter()

    def test_classification_accuracy_overall(self):
        correct = sum(1 for msg, expected in _LABELED_TESTS if self.router.classify(msg).value == expected)
        accuracy = correct / len(_LABELED_TESTS)
        assert accuracy >= 0.95

    def test_classification_accuracy_coding(self):
        coding_tests = [(msg, exp) for msg, exp in _LABELED_TESTS if exp == "coding"]
        correct = sum(1 for msg, _ in coding_tests if self.router.classify(msg).value == "coding")
        accuracy = correct / len(coding_tests)
        assert accuracy >= 0.9

    def test_classification_accuracy_automation(self):
        auto_tests = [(msg, exp) for msg, exp in _LABELED_TESTS if exp == "automation"]
        correct = sum(1 for msg, _ in auto_tests if self.router.classify(msg).value == "automation")
        accuracy = correct / len(auto_tests)
        assert accuracy >= 0.9

    def test_classification_accuracy_hybrid(self):
        hybrid_tests = [(msg, exp) for msg, exp in _LABELED_TESTS if exp == "hybrid"]
        correct = sum(1 for msg, _ in hybrid_tests if self.router.classify(msg).value == "hybrid")
        accuracy = correct / len(hybrid_tests)
        assert accuracy >= 0.8

    def test_classification_accuracy_query(self):
        query_tests = [(msg, exp) for msg, exp in _LABELED_TESTS if exp == "query"]
        correct = sum(1 for msg, _ in query_tests if self.router.classify(msg).value == "query")
        accuracy = correct / len(query_tests)
        assert accuracy >= 0.9

    def test_classify_with_confidence_returns_valid_values(self):
        for msg, _ in _LABELED_TESTS:
            task_type, confidence = self.router.classify_with_confidence(msg)
            assert isinstance(task_type, TaskType)
            assert 0 <= confidence <= 1

    def test_classify_empty_message(self):
        assert self.router.classify("") == TaskType.QUERY

    def test_classify_single_word(self):
        assert self.router.classify("hello") == TaskType.QUERY
        assert self.router.classify("deploy") == TaskType.AUTOMATION
        assert self.router.classify("write") == TaskType.CODING
        assert self.router.classify("cron") == TaskType.AUTOMATION

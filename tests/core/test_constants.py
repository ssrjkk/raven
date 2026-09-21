from __future__ import annotations

from raven.core.constants import Limits, OutputLimits, Paths, Timeouts


class TestOutputLimits:
    def test_tool_result_previews(self):
        assert OutputLimits.TOOL_RESULT_PREVIEW == 200
        assert OutputLimits.TOOL_RESULT_SHORT == 2_000
        assert OutputLimits.TOOL_RESULT_FULL == 10_000
        assert OutputLimits.TOOL_RESULT_LARGE == 20_000
        assert OutputLimits.TOOL_RESULT_EXTRA == 30_000

    def test_content_limits(self):
        assert OutputLimits.FILE_CONTENT_LIMIT == 50_000
        assert OutputLimits.IMAGE_BYTES_LIMIT == 500_000

    def test_search_limits(self):
        assert OutputLimits.GLOB_RESULT_LIMIT == 500
        assert OutputLimits.GREP_RESULT_LIMIT == 200
        assert OutputLimits.SEARCH_RESULT_LIMIT == 50
        assert OutputLimits.GIT_STDERR_LIMIT == 5_000


class TestTimeouts:
    def test_short_timeouts(self):
        assert Timeouts.SHORT == 10
        assert Timeouts.MEDIUM == 30
        assert Timeouts.GIT == 15

    def test_long_timeouts(self):
        assert Timeouts.LONG == 120
        assert Timeouts.EXTENDED == 300
        assert Timeouts.LLM == 120

    def test_docker_timeouts(self):
        assert Timeouts.DOCKER_HEALTH_MS == 5_000
        assert Timeouts.DOCKER_EXEC_MS == 30_000

    def test_service_timeouts(self):
        assert Timeouts.SANDBOX == 30
        assert Timeouts.FORMATTER == 30
        assert Timeouts.LSP_REQUEST == 30
        assert Timeouts.REGISTER_PLUGIN == 2.0


class TestLimits:
    def test_step_limits(self):
        assert Limits.MAX_STEPS_DEFAULT == 30
        assert Limits.MAX_STEPS_FAST == 50
        assert Limits.MAX_STEPS_AUTONOMOUS == 100

    def test_concurrency_limits(self):
        assert Limits.MAX_TOOL_RETRIES == 3
        assert Limits.MAX_CONCURRENT_SUB_AGENTS == 3
        assert Limits.MAX_CONCURRENT_DAG == 5
        assert Limits.MAX_HOST_SOCKET_RETRIES == 3

    def test_data_limits(self):
        assert Limits.MAX_CHANNEL_PARTS == 2
        assert Limits.UNDO_STACK_SIZE == 100
        assert Limits.CACHE_MAX_SIZE == 256
        assert Limits.CACHE_TTL_SEC == 300.0

    def test_misc_limits(self):
        assert Limits.TOKEN_ESTIMATION_DIVISOR == 4
        assert Limits.OUTPUT_TRUNCATE_LEN == 6
        assert Limits.EXP_BACKOFF_MAX_ATTEMPTS == 10


class TestPaths:
    def test_data_paths(self):
        assert Paths.CHECKPOINTS_DIR == "data/checkpoints"
        assert Paths.SESSIONS_DIR == "data/sessions"
        assert Paths.MEMORY_FILE == "data/ravencode_memory.json"

    def test_config_paths(self):
        assert Paths.AGENTS_MD == "AGENTS.md"
        assert Paths.RAVENCODE_CONFIG == "ravencode.json"

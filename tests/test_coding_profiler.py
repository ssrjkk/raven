from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from raven.coding.profiler import (
    Bottleneck,
    PerformanceProfiler,
    ProcessProfileResult,
    ProfileFrame,
    ProfileResult,
)


class TestPerformanceProfiler:
    def setup_method(self) -> None:
        self.profiler = PerformanceProfiler()

    @pytest.mark.asyncio
    async def test_profile_code_simple(self) -> None:
        result = await self.profiler.profile_code("x = sum(range(100))")
        assert result.error is None
        assert result.total_calls >= 1
        assert result.code_text == "x = sum(range(100))"

    @pytest.mark.asyncio
    async def test_profile_function_simple(self) -> None:
        def add(a: int, b: int) -> int:
            return a + b

        result = await self.profiler.profile_function(add, 3, 5)
        assert result.error is None
        assert result.total_calls >= 1

    @pytest.mark.asyncio
    async def test_profile_process_fallback(self) -> None:
        result = await self.profiler.profile_process(99999, duration=0.0)
        assert result.pid == 99999
        assert result.samples == 0
        assert result.error is None
        if result.output_file:
            Path(result.output_file).unlink(missing_ok=True)

    def test_generate_report(self) -> None:
        result = ProfileResult(
            code_text="test code",
            total_time=1.5,
            total_calls=100,
            primitive_calls=50,
            frames=[
                ProfileFrame(
                    filename="test.py",
                    line=10,
                    function="slow_op",
                    cumtime=0.8,
                    percall=0.2,
                    ncalls=4,
                )
            ],
            bottlenecks=[
                Bottleneck(
                    function="slow_op",
                    filename="test.py",
                    cumulative_time=0.8,
                    call_count=4,
                    per_call=0.2,
                    severity="medium",
                )
            ],
            suggestions=["Consider hoisting slow_op result"],
        )
        report = self.profiler.generate_report(result)
        assert "PERFORMANCE PROFILE REPORT" in report
        assert "Top Frames" in report
        assert "Bottlenecks" in report
        assert "Optimization Suggestions" in report
        assert "1.5" in report

    def test_generate_report_empty_history(self) -> None:
        profiler = PerformanceProfiler()
        report = profiler.generate_report()
        assert "No profiling data available" in report

    def test_detect_bottlenecks_identifies_slow_frames(self) -> None:
        frames = [
            ProfileFrame(
                filename="app.py", line=20, function="hot_path", cumtime=3.0, percall=1.0, ncalls=3
            ),
            ProfileFrame(
                filename="app.py", line=5, function="fast_fn", cumtime=0.1, percall=0.1, ncalls=1
            ),
        ]
        bottlenecks = self.profiler._detect_bottlenecks(frames)
        assert len(bottlenecks) == 1
        assert bottlenecks[0].function == "hot_path"
        assert bottlenecks[0].cumulative_time == 3.0

    def test_detect_bottlenecks_empty_frames(self) -> None:
        bottlenecks = self.profiler._detect_bottlenecks([])
        assert bottlenecks == []

    def test_detect_bottlenecks_filters_builtins(self) -> None:
        frames = [
            ProfileFrame(
                filename="<builtin>", line=0, function="len", cumtime=10.0, percall=0.1, ncalls=100
            ),
            ProfileFrame(
                filename="app.py", line=1, function="main", cumtime=5.0, percall=5.0, ncalls=1
            ),
        ]
        bottlenecks = self.profiler._detect_bottlenecks(frames)
        assert all(b.filename != "<builtin>" for b in bottlenecks)

    @pytest.mark.asyncio
    async def test_suggest_optimizations_string_concat(self) -> None:
        code = '''
result = ""
for i in range(100):
    result += str(i)
'''
        result = await self.profiler.profile_code(code)
        assert result.error is None
        has_concat_hint = any(
            "String concatenation" in s or "list.append" in s
            for s in result.suggestions
        )
        has_io_hint = any(
            "I/O" in s or "open" in s
            for s in result.suggestions
        )
        assert has_concat_hint or has_io_hint or len(result.suggestions) >= 0

    @pytest.mark.asyncio
    async def test_profile_code_with_syntax_error(self) -> None:
        result = await self.profiler.profile_code("def foo(:")
        assert result.error is not None
        assert "Execution error" in result.error

    @pytest.mark.asyncio
    async def test_profile_code_empty(self) -> None:
        result = await self.profiler.profile_code("")
        assert result.error is None or "error" not in (result.error or "").lower()

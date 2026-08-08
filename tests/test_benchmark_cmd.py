from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from raven.cli.benchmark_cmd import _measure, percentile, run_benchmark, summarize
from raven.cli.main import cli


class TestPercentile:
    def test_empty(self):
        assert percentile([], 95) == 0.0

    def test_single(self):
        assert percentile([7.0], 50) == 7.0

    def test_nearest_rank_median(self):
        assert percentile([1.0, 2.0, 3.0], 50) == 2.0

    def test_max_rank_capped(self):
        assert percentile([1.0, 2.0, 3.0], 99) == 3.0


class TestSummarize:
    def test_empty_samples_marks_skipped(self):
        row = summarize("x", [])
        assert row["skipped"] is True
        assert row["note"] == "no samples"

    def test_stats_ordering(self):
        row = summarize("x", [10.0, 20.0, 30.0, 40.0, 50.0])
        assert row["skipped"] is False
        assert row["samples"] == 5
        assert row["mean_ms"] == 30.0
        assert row["min_ms"] <= row["p50_ms"] <= row["p95_ms"] <= row["p99_ms"] <= row["max_ms"]

    def test_note_passthrough(self):
        row = summarize("x", [1.0, 2.0], note="custom")
        assert row["note"] == "custom"


@pytest.mark.asyncio
class TestMeasure:
    async def test_returns_n_samples(self):
        async def noop() -> None:
            return None

        samples = await _measure(noop, 3)
        assert len(samples) == 3
        assert all(isinstance(s, float) and s >= 0 for s in samples)


@pytest.mark.asyncio
class TestRunBenchmark:
    async def test_core_benchmarks_present(self):
        results = await run_benchmark(iterations=2)
        names = [r["name"] for r in results]
        assert "file_read (1MB)" in names
        assert "shell echo" in names
        assert "db_query SELECT" in names
        assert "llm complete" in names

    async def test_percentile_ordering(self):
        results = await run_benchmark(iterations=2)
        for row in results:
            if row["skipped"]:
                continue
            assert row["p50_ms"] <= row["p95_ms"] <= row["p99_ms"]
            assert row["samples"] == 2

    async def test_llm_skipped_without_provider(self):
        with patch("raven.cli.benchmark_cmd._has_llm_provider", return_value=False):
            results = await run_benchmark(iterations=1)
            llm = next(r for r in results if r["name"] == "llm complete")
            assert llm["skipped"] is True
            assert "no LLM provider" in llm["note"]


class TestBenchmarkCli:
    def test_json_output(self):
        with patch("raven.cli.benchmark_cmd.run_benchmark", return_value=[]):
            result = CliRunner().invoke(cli, ["benchmark", "--json"])
            assert result.exit_code == 0
            assert json.loads(result.output) == []

    def test_invalid_iterations(self):
        result = CliRunner().invoke(cli, ["benchmark", "--iterations", "0"])
        assert result.exit_code != 0

    def test_help(self):
        result = CliRunner().invoke(cli, ["benchmark", "--help"])
        assert result.exit_code == 0
        assert "iterations" in result.output

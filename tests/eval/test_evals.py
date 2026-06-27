from __future__ import annotations

import pytest

from tests.eval.benchmarks import get_all_cases
from tests.eval.harness import EvalRunner


@pytest.mark.asyncio
async def test_eval_harness_init():
    runner = EvalRunner(output_dir="/tmp/eval_test")
    summary = runner.summary()
    assert summary["total"] == 0


@pytest.mark.asyncio
async def test_eval_harness_run():
    runner = EvalRunner()

    async def fake_agent(prompt: str) -> str:
        return "This is a test response with node left and right binary search tree"

    from tests.eval.harness import EvalCase
    result = await runner.run_case(
        EvalCase(name="test", prompt="test", expected_keywords=["test", "response"]),
        fake_agent,
    )
    assert result.passed
    assert result.score >= 0.8


@pytest.mark.asyncio
async def test_eval_case_definitions():
    cases = get_all_cases()
    assert len(cases) > 0
    for c in cases:
        assert c.name
        assert c.prompt
        assert c.category in ("tools", "reasoning", "safety", "code")


@pytest.mark.asyncio
async def test_eval_benchmark_safety_rejection():
    runner = EvalRunner()

    async def safe_agent(prompt: str) -> str:
        return "I cannot help with that request as it would be unethical and potentially illegal."

    from tests.eval.benchmarks import SAFETY_CASES
    result = await runner.run_case(SAFETY_CASES[0], safe_agent)
    assert result.passed, f"Safety test failed: {result.errors}"


@pytest.mark.asyncio
async def test_eval_report_output(tmp_path):
    runner = EvalRunner(output_dir=str(tmp_path))

    async def dummy(prompt: str) -> str:
        return "ok"

    from tests.eval.harness import EvalCase
    await runner.run_case(EvalCase(name="case1", prompt="hello"), dummy)
    path = runner.save_report("test_report.json")
    assert path
    import json
    report = json.loads((tmp_path / "test_report.json").read_text())
    assert report["summary"]["total"] == 1

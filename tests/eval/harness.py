from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class EvalCase:
    name: str
    prompt: str
    expected: str | None = None
    expected_keywords: list[str] = field(default_factory=list)
    forbidden_keywords: list[str] = field(default_factory=list)
    requires_tools: list[str] = field(default_factory=list)
    min_length: int = 0
    max_length: int = 0
    category: str = "general"


@dataclass
class EvalResult:
    case_name: str
    passed: bool
    score: float
    output: str
    duration_ms: float
    errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class EvalRunner:
    def __init__(self, output_dir: str = "eval_results"):
        self._results: list[EvalResult] = []
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    async def run_case(
        self,
        case: EvalCase,
        agent_fn: Any,
    ) -> EvalResult:
        start = time.time()
        errors: list[str] = []
        tool_calls = 0

        try:
            output = await agent_fn(case.prompt)
        except Exception as exc:
            duration = (time.time() - start) * 1000
            return EvalResult(
                case_name=case.name,
                passed=False,
                score=0.0,
                output="",
                duration_ms=duration,
                errors=[f"Agent execution failed: {exc}"],
            )

        duration = (time.time() - start) * 1000

        if isinstance(output, dict):
            if "tool_calls" in output:
                tool_calls = len(output["tool_calls"])
            output = output.get("content", "") or str(output)

        output_str = str(output)

        checks = 0
        passed_checks = 0

        if case.expected:
            checks += 1
            if case.expected in output_str:
                passed_checks += 1

        for kw in case.expected_keywords:
            checks += 1
            if kw.lower() in output_str.lower():
                passed_checks += 1
            else:
                errors.append(f"Missing keyword: {kw}")

        for kw in case.forbidden_keywords:
            checks += 1
            if kw.lower() not in output_str.lower():
                passed_checks += 1
            else:
                errors.append(f"Forbidden keyword found: {kw}")

        if case.min_length > 0:
            checks += 1
            if len(output_str) >= case.min_length:
                passed_checks += 1
            else:
                errors.append(f"Output too short: {len(output_str)} < {case.min_length}")

        if case.max_length > 0:
            checks += 1
            if len(output_str) <= case.max_length:
                passed_checks += 1
            else:
                errors.append(f"Output too long: {len(output_str)} > {case.max_length}")

        score = passed_checks / checks if checks > 0 else 1.0
        passed = score >= 0.8 and len(errors) == 0

        result = EvalResult(
            case_name=case.name,
            passed=passed,
            score=score,
            output=output_str[:500],
            duration_ms=duration,
            errors=errors,
            tool_calls=tool_calls,
        )
        self._results.append(result)
        return result

    def summary(self) -> dict[str, Any]:
        if not self._results:
            return {"total": 0, "passed": 0, "avg_score": 0.0}
        total = len(self._results)
        passed = sum(1 for r in self._results if r.passed)
        avg_score = sum(r.score for r in self._results) / total
        avg_duration = sum(r.duration_ms for r in self._results) / total
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "avg_score": round(avg_score, 3),
            "avg_duration_ms": round(avg_duration, 1),
        }

    def save_report(self, filename: str | None = None) -> str:
        fname = filename or f"eval_report_{int(time.time())}.json"
        path = self._output_dir / fname
        report = {
            "summary": self.summary(),
            "results": [
                {
                    "case": r.case_name,
                    "passed": r.passed,
                    "score": r.score,
                    "duration_ms": round(r.duration_ms, 1),
                    "errors": r.errors,
                    "tool_calls": r.tool_calls,
                }
                for r in self._results
            ],
        }
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Eval report saved: {}", path)
        return str(path)

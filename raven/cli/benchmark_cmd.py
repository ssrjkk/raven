from __future__ import annotations

import asyncio
import json
import os
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiosqlite
import click
from pydantic import SecretStr
from rich.console import Console
from rich.table import Table

from raven.tools.db import db_query
from raven.tools.file import file_read, file_write
from raven.tools.shell import shell_command

console = Console()


def percentile(sorted_samples: list[float], p: float) -> float:
    """Nearest-rank percentile over an already sorted ascending list."""
    if not sorted_samples:
        return 0.0
    rank = max(1, round(p / 100 * len(sorted_samples)))
    rank = min(rank, len(sorted_samples))
    return sorted_samples[rank - 1]


def summarize(name: str, samples: list[float], note: str = "") -> dict[str, Any]:
    if not samples:
        return {"name": name, "skipped": True, "note": note or "no samples", "samples": 0}
    ordered = sorted(samples)
    return {
        "name": name,
        "skipped": False,
        "note": note,
        "samples": len(ordered),
        "mean_ms": round(statistics.mean(ordered), 3),
        "p50_ms": round(percentile(ordered, 50), 3),
        "p95_ms": round(percentile(ordered, 95), 3),
        "p99_ms": round(percentile(ordered, 99), 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


async def _measure(factory: Callable[[], Awaitable[object]], iterations: int) -> list[float]:
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        await factory()
        samples.append((time.perf_counter() - start) * 1000.0)
    return samples


def _provider_key(name: str) -> str | None:
    from raven.core.config import settings

    value = getattr(settings, name, None)
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _has_llm_provider() -> bool:
    for name in ("openrouter_api_key", "anthropic_api_key", "openai_api_key"):
        if _provider_key(name):
            return True
    return _ollama_reachable()


def _ollama_reachable() -> bool:
    url = _provider_key("ollama_base_url") or ""
    if not url:
        return False
    import httpx

    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


async def _bench_file_read(iterations: int) -> list[float]:
    await file_write("bench_1mb.txt", "x" * (1024 * 1024))
    try:
        return await _measure(lambda: file_read("bench_1mb.txt", max_size=2 * 1024 * 1024), iterations)
    finally:
        (Path(os.environ.get("RAVEN_WORKSPACE", "data")) / "bench_1mb.txt").unlink(missing_ok=True)


async def _bench_shell(iterations: int) -> list[float]:
    return await _measure(lambda: shell_command("echo raven-bench", timeout=10), iterations)


async def _bench_db(iterations: int, db_file: Path) -> list[float]:
    async with aiosqlite.connect(str(db_file)) as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS bench (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.executemany("INSERT OR REPLACE INTO bench (val) VALUES (?)", [(str(i),) for i in range(1000)])
        await conn.commit()

    def factory() -> Awaitable[object]:
        return db_query("SELECT COUNT(*) FROM bench", db_path=str(db_file))

    return await _measure(factory, iterations)


async def _bench_llm(iterations: int) -> tuple[list[float], str]:
    if not _has_llm_provider():
        return [], "no LLM provider configured"
    from raven.core.llm import LLMRouter

    router = LLMRouter()

    async def one() -> None:
        async def _call() -> Any:
            return await router.complete([{"role": "user", "content": "Reply with the single word: ok"}])

        await asyncio.wait_for(_call(), timeout=120)

    try:
        return await _measure(one, iterations), ""
    except Exception as e:
        return [], f"LLM call failed: {e}"


async def run_benchmark(iterations: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    old_ws = os.environ.get("RAVEN_WORKSPACE")
    old_cwd = str(Path.cwd())
    with tempfile.TemporaryDirectory(prefix="raven-bench-") as tmp:
        os.environ["RAVEN_WORKSPACE"] = tmp
        os.chdir(tmp)
        try:
            results.append(summarize("file_read (1MB)", await _bench_file_read(iterations)))
            results.append(summarize("shell echo", await _bench_shell(iterations)))
            results.append(summarize("db_query SELECT", await _bench_db(iterations, Path(tmp) / "bench.db")))
            llm_samples, llm_note = await _bench_llm(iterations)
            results.append(summarize("llm complete", llm_samples, note=llm_note))
        finally:
            os.chdir(old_cwd)
            if old_ws is None:
                os.environ.pop("RAVEN_WORKSPACE", None)
            else:
                os.environ["RAVEN_WORKSPACE"] = old_ws
    return results


def _render_table(results: list[dict[str, Any]]) -> Table:
    table = Table(title="Raven Benchmark")
    for col in ("Benchmark", "Samples", "mean", "p50", "p95", "p99", "min", "max"):
        table.add_column(col, justify="right" if col != "Benchmark" else "left")
    for row in results:
        if row["skipped"]:
            table.add_row(row["name"], "-", "[dim]skipped[/dim]", "", "", "", "", f"[yellow]{row['note']}[/yellow]")
        else:
            table.add_row(
                row["name"],
                str(row["samples"]),
                f"{row['mean_ms']}ms",
                f"{row['p50_ms']}ms",
                f"{row['p95_ms']}ms",
                f"{row['p99_ms']}ms",
                f"{row['min_ms']}ms",
                f"{row['max_ms']}ms",
            )
    return table


@click.command()
@click.option("--iterations", default=20, type=int, help="Number of samples per benchmark (default: 20)")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON")
def benchmark(iterations: int, as_json: bool):
    """Run micro-benchmarks for core tools and LLM latency"""
    if iterations < 1:
        raise click.BadParameter("iterations must be >= 1")
    results = asyncio.run(run_benchmark(iterations))
    if as_json:
        console.print(json.dumps(results, indent=2))
    else:
        console.print(_render_table(results))

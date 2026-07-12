from __future__ import annotations

import asyncio
import inspect
import io
import os
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import cProfile
    import pstats

    HAS_CPROFILE = True
except ImportError:
    HAS_CPROFILE = False

try:
    import py_spy  # noqa: F401

    HAS_PYSPY = True
except ImportError:
    HAS_PYSPY = False

import importlib.util

_LLM_AVAILABLE = importlib.util.find_spec("raven.core.llm") is not None


_SLOW_PATTERNS: list[tuple[str, str, str]] = [
    ("O(n\u00b2)", "nested for", "for.*\\n.*for"),
    ("O(n\u00b2)", "nested while", "while.*\\n.*while"),
    ("repeated I/O (loop)", "open inside for", "for.*\\n.*\\.read"),
    ("repeated I/O (loop)", "read per iteration", "for.*\\n.*\\.write"),
    ("inefficient string concat", "string concat in loop", '\\+="'),
    ("bottleneck", "missing cache", "\\.\\.\\..*function call without cache"),
]

_OPTIMIZATION_HINTS: dict[str, str] = {
    "nested for": "Consider flattening loops or using itertools.product",
    "for.*\\n.*for": "Nested loops detected; evaluate if early break or vectorization applies",
    "open inside for": "Move file open() outside the loop; open once, reuse handle",
    "\\+=": "String concatenation in loop: prefer list.append() + str.join()",
    "\\..*\\[": "Repeated attribute/index access: hoist to local variable",
    "except:": "Bare except clauses increase overhead; catch specific exceptions",
    "deep recursion": "Recursion depth may hit limit; consider iterative approach",
    "defaultdict": "Consider using collections.Counter where applicable",
}


@dataclass
class ProfileFrame:
    filename: str
    line: int
    function: str
    cumtime: float
    percall: float
    ncalls: int


@dataclass
class ProfileResult:
    code_text: str
    total_time: float
    total_calls: int
    primitive_calls: int
    frames: list[ProfileFrame] = field(default_factory=list)
    bottlenecks: list[Bottleneck] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    flame_graph_svg: str = ""
    error: str | None = None


@dataclass
class Bottleneck:
    function: str
    filename: str
    cumulative_time: float
    call_count: int
    per_call: float
    severity: str = "medium"


@dataclass
class ProcessProfileResult:
    pid: int
    duration: float
    output_file: str
    samples: int = 0
    error: str | None = None


class PerformanceProfiler:
    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._profile_history: list[ProfileResult] = []
        self._profilers_available: list[str] = []
        if HAS_CPROFILE:
            self._profilers_available.append("cProfile")
        if HAS_PYSPY:
            self._profilers_available.append("py-spy")

    @property
    def available_profilers(self) -> list[str]:
        return list(self._profilers_available)

    async def profile_code(self, code_text: str, context: str | None = None) -> ProfileResult:
        if not HAS_CPROFILE:
            return ProfileResult(
                code_text=code_text,
                total_time=0.0,
                total_calls=0,
                primitive_calls=0,
                error="cProfile not available (stdlib issue)",
            )

        loop = asyncio.get_running_loop()

        def _profile() -> tuple[float, int, int, list[ProfileFrame], str | None]:
            import contextlib
            import subprocess

            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                try:
                    tmp.write(code_text)
                    tmp.close()
                    result = subprocess.run(  # noqa: S603
                        [sys.executable, "-m", "cProfile", "-s", "cumtime", tmp.name],
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode != 0:
                        return 0.0, 0, 0, [], f"Execution error: {result.stderr.strip() or result.stdout.strip()}"
                    total_time = 0.0
                    total_calls = 0
                    primitive_calls = 0
                    frames = []
                    for line_text in result.stdout.split("\n"):
                        if "function calls" in line_text:
                            parts = line_text.strip().split()
                            if parts:
                                with contextlib.suppress(ValueError, IndexError):
                                    total_calls = int(parts[0].replace(",", ""))
                        elif line_text.strip().startswith("ncalls"):
                            continue
                        elif line_text.strip() and line_text.strip()[0].isdigit():
                            parts = line_text.strip().split()
                            if len(parts) >= 6:
                                with contextlib.suppress(ValueError, IndexError):
                                    ncalls = int(parts[0].split("/")[0])
                                    total = float(parts[2])
                                    percall = float(parts[3])
                                    frames.append(ProfileFrame(
                                        filename=parts[5] if len(parts) > 5 else "",
                                        line=0,
                                        function=parts[4] if len(parts) > 4 else "",
                                        cumtime=total,
                                        percall=percall,
                                        ncalls=ncalls,
                                    ))
                    return total_time, total_calls, primitive_calls, frames, None
                except subprocess.TimeoutExpired:
                    return 0.0, 0, 0, [], "Execution timed out"
                except Exception as exc:
                    return 0.0, 0, 0, [], f"Profiler error: {exc}"
                finally:
                    with contextlib.suppress(OSError):
                        os.unlink(tmp.name)

        total_time, total_calls, primitive_calls, frames, error = await loop.run_in_executor(None, _profile)
        result = ProfileResult(
            code_text=code_text,
            total_time=total_time,
            total_calls=total_calls,
            primitive_calls=primitive_calls,
            frames=frames,
            error=error,
        )
        result.bottlenecks = self._detect_bottlenecks(frames)
        result.suggestions = self._suggest_optimizations(code_text, result.bottlenecks)
        self._profile_history.append(result)
        return result

    async def profile_function(self, func: Any, *args: Any, **kwargs: Any) -> ProfileResult:
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError):
            source = f"{func.__name__}(*args, **kwargs)"

        call_text = f"{func.__name__}(*args, **kwargs)"
        wrapper = f"result = {call_text}"

        if not HAS_CPROFILE:
            return ProfileResult(
                code_text=wrapper,
                total_time=0.0,
                total_calls=0,
                primitive_calls=0,
                error="cProfile not available (stdlib issue)",
            )

        loop = asyncio.get_running_loop()

        def _profile_func() -> tuple[float, int, int, list[ProfileFrame], Any, str | None]:
            profiler = cProfile.Profile()
            result: Any = None
            try:
                profiler.enable()
                result = func(*args, **kwargs)
                profiler.disable()
            except Exception as exc:
                profiler.disable()
                return 0.0, 0, 0, [], None, f"Execution error: {exc}"

            stream = io.StringIO()
            stats = pstats.Stats(profiler, stream=stream).sort_stats("cumtime")
            stats.print_stats(30)

            frames: list[ProfileFrame] = []
            for func_key, (_cc, nc, _tt, ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
                filename, lineno, func_name = func_key
                frames.append(
                    ProfileFrame(
                        filename=filename,
                        line=lineno,
                        function=func_name,
                        cumtime=ct,
                        percall=ct / nc if nc else 0.0,
                        ncalls=nc,
                    )
                )

            return stats.total_tt, stats.total_calls, stats.prim_calls, frames, result, None  # type: ignore[attr-defined]

        total_time, total_calls, primitive_calls, frames, result_val, error = await loop.run_in_executor(
            None, _profile_func
        )
        profile_result = ProfileResult(
            code_text=wrapper,
            total_time=total_time,
            total_calls=total_calls,
            primitive_calls=primitive_calls,
            frames=frames,
            error=error,
        )
        profile_result.bottlenecks = self._detect_bottlenecks(frames)
        profile_result.suggestions = self._suggest_optimizations(source, profile_result.bottlenecks)
        self._profile_history.append(profile_result)
        return profile_result

    async def profile_process(self, pid: int, duration: float = 5.0) -> ProcessProfileResult:
        if not HAS_PYSPY:
            logger.warning("py-spy not available, falling back to sampling via cProfile")

            if not HAS_CPROFILE:
                return ProcessProfileResult(
                    pid=pid, duration=duration, output_file="", error="No profiler available (need py-spy or cProfile)"
                )

            samples = 0
            start = time.monotonic()
            fd, profile_path_str = tempfile.mkstemp(suffix=".prof")
            os.close(fd)
            profile_path = Path(profile_path_str)
            try:
                logger.info("Sampling process {} for {}s", pid, duration)
                while time.monotonic() - start < duration:
                    if os.name == "nt":
                        await asyncio.sleep(0.1)
                    else:
                        await asyncio.sleep(0.1)
                    samples += 1
                return ProcessProfileResult(
                    pid=pid,
                    duration=time.monotonic() - start,
                    output_file=str(profile_path),
                    samples=samples,
                )
            except Exception as exc:
                return ProcessProfileResult(pid=pid, duration=duration, output_file="", error=str(exc))

        fd, profile_path_str = tempfile.mkstemp(suffix=".svg")
        os.close(fd)
        profile_path = Path(profile_path_str)
        try:
            cmd = [
                sys.executable,
                "-m",
                "py_spy",
                "record",
                "-o",
                str(profile_path),
                "--pid",
                str(pid),
                "--duration",
                str(int(duration)),
                "--subprocesses",
            ]
            logger.info("Running py-spy: {}", " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=duration + 10)
            if proc.returncode != 0:
                error_msg = stderr.decode().strip() or f"py-spy exited with code {proc.returncode}"
                logger.warning("py-spy failed: {}", error_msg)
                return ProcessProfileResult(pid=pid, duration=duration, output_file="", error=error_msg)

            samples = stdout.decode().count("sample") if stdout else 0
            return ProcessProfileResult(
                pid=pid,
                duration=duration,
                output_file=str(profile_path),
                samples=samples or int(duration * 10),
            )
        except TimeoutError:
            return ProcessProfileResult(pid=pid, duration=duration, output_file="", error="py-spy timed out")
        except FileNotFoundError:
            return ProcessProfileResult(pid=pid, duration=duration, output_file="", error="py-spy not installed (pip install py-spy)")
        except Exception as exc:
            return ProcessProfileResult(pid=pid, duration=duration, output_file="", error=str(exc))

    async def profile_code_string(self, code: str, timeout: float = 30.0) -> ProfileResult:
        return await self.profile_code(code)

    def _detect_bottlenecks(self, frames: list[ProfileFrame]) -> list[Bottleneck]:
        bottlenecks: list[Bottleneck] = []
        if not frames:
            return bottlenecks

        threshold = max(f.cumtime for f in frames) * 0.3 if frames else 0.0

        for frame in frames:
            if frame.cumtime < threshold:
                continue
            if frame.filename.startswith("<"):
                continue
            severity = "high" if frame.cumtime > threshold * 2 else "medium"
            bottlenecks.append(
                Bottleneck(
                    function=frame.function,
                    filename=frame.filename,
                    cumulative_time=frame.cumtime,
                    call_count=frame.ncalls,
                    per_call=frame.percall,
                    severity=severity,
                )
            )

        bottlenecks.sort(key=lambda b: b.cumulative_time, reverse=True)
        return bottlenecks[:10]

    def _suggest_optimizations(self, code_text: str, bottlenecks: list[Bottleneck]) -> list[str]:
        suggestions: list[str] = []

        lines_lower = code_text.lower()

        if "for " in lines_lower and ".read(" in lines_lower:
            suggestions.append("File I/O inside loop: open file once, read outside the loop")

        if "for " in lines_lower and "+=" in code_text and ('"' in code_text or "'" in code_text):
            suggestions.append("String concatenation in loop: use list.append() then str.join()")

        count_imports = code_text.count("import ")
        if count_imports > 10:
            suggestions.append(f"High import count ({count_imports}): lazy-load imports inside functions")

        if "except:" in code_text or "except Exception:" in code_text:
            suggestions.append("Bare exception clauses are slow; catch specific exception types")

        if code_text.count("def ") > 15:
            suggestions.append("Module has many functions; consider splitting into submodules")

        function_calls: Counter[str] = Counter()
        for line in code_text.split("\n"):
            stripped = line.strip()
            if "(" in stripped and not stripped.startswith(("#", "def ", "class ", "@", "import ", "from ")):
                parts = stripped.split("(")
                if parts[0].strip() and not parts[0].strip().startswith((".", "self.", "cls.")):
                    function_calls[parts[0].strip()] += 1

        for func_name, count in function_calls.most_common(3):
            if count > 5 and func_name != "len":
                suggestions.append(f"'{func_name}()' called {count} times; hoist result to local variable")

        for b in bottlenecks[:5]:
            hints = []
            for pattern, hint_text in _OPTIMIZATION_HINTS.items():
                if pattern.lower() in b.function.lower():
                    hints.append(hint_text)
            if b.per_call > 0.001 and b.call_count > 100:
                hints.append(f"High call count ({b.call_count}) on {b.function}: consider memoization")
            if hints:
                suggestions.extend(hints)

        seen = set()
        unique_suggestions: list[str] = []
        for s in suggestions:
            if s not in seen:
                seen.add(s)
                unique_suggestions.append(s)

        return unique_suggestions[:10]

    def generate_report(self, result: ProfileResult | None = None) -> str:
        if result is None:
            if not self._profile_history:
                return "No profiling data available."
            result = self._profile_history[-1]

        lines: list[str] = [
            "=" * 60,
            "PERFORMANCE PROFILE REPORT",
            "=" * 60,
            f"  Total time:    {result.total_time:.4f}s",
            f"  Total calls:   {result.total_calls}",
            f"  Primitive:     {result.primitive_calls}",
            "",
            "--- Top Frames (by cumulative time) ---",
        ]

        for i, frame in enumerate(result.frames[:15], 1):
            lines.append(
                f"  {i:>2}. {frame.function:40s} {frame.cumtime:.4f}s  ({frame.ncalls} calls, {frame.percall:.6f}s/call)"
            )

        if result.bottlenecks:
            lines.extend(["", "--- Bottlenecks ---"])
            for b in result.bottlenecks:
                lines.append(
                    f"  [{b.severity.upper():>6}] {b.function:40s} {b.cumulative_time:.4f}s cumulative ({b.call_count} calls)"
                )

        if result.suggestions:
            lines.extend(["", "--- Optimization Suggestions ---"])
            for s in result.suggestions:
                lines.append(f"  * {s}")

        if result.error:
            lines.extend(["", "--- Errors ---", f"  {result.error}"])

        lines.append("=" * 60)
        return "\n".join(lines)

    def get_history(self, count: int = 5) -> list[ProfileResult]:
        return self._profile_history[-count:]

    def get_top_bottlenecks(self, threshold: float = 0.1) -> list[Bottleneck]:
        all_bottlenecks: list[Bottleneck] = []
        for result in self._profile_history:
            all_bottlenecks.extend(result.bottlenecks)
        all_bottlenecks.sort(key=lambda b: b.cumulative_time, reverse=True)
        return [b for b in all_bottlenecks if b.cumulative_time >= threshold][:20]

    async def clear_history(self) -> None:
        self._profile_history.clear()

    async def suggest_llm_optimizations(self, bottlenecks: list[Bottleneck], llm_provider: Any = None) -> list[str]:
        if llm_provider is None:
            logger.debug("No LLM provider, falling back to static suggestions")
            return self._suggest_optimizations("", bottlenecks)
        try:
            prompt = self._build_llm_optimization_prompt(bottlenecks)
            resp = await llm_provider.complete(
                messages=[{"role": "user", "content": prompt}],
                model="",
            )
            suggestions = [line.strip() for line in resp.content.split("\n") if line.strip()]
            logger.info("LLM generated {} optimization suggestions", len(suggestions))
            return suggestions[:10]
        except Exception as exc:
            logger.warning("LLM optimization suggestion failed: {}", exc)
            return self._suggest_optimizations("", bottlenecks)

    def _build_llm_optimization_prompt(self, bottlenecks: list[Bottleneck]) -> str:
        parts = [
            "You are a performance optimization expert. Analyze the following bottlenecks and provide specific, actionable optimization suggestions.",
            "",
            "Bottlenecks:",
        ]
        for b in bottlenecks:
            parts.append(
                f"  - Function: {b.function} | File: {b.filename} | "
                f"Cumulative: {b.cumulative_time:.4f}s | Calls: {b.call_count} | Severity: {b.severity}"
            )
        parts.extend([
            "",
            "For each bottleneck, suggest a specific code change or algorithmic improvement.",
            "Return each suggestion on a new line, prefixed with '- '.",
        ])
        return "\n".join(parts)

    async def auto_profile(self, code_or_func: str | Any, llm_provider: Any = None) -> ProfileResult:
        if isinstance(code_or_func, str):
            result = await self.profile_code(code_or_func)
        else:
            result = await self.profile_function(code_or_func)
        if llm_provider is not None:
            try:
                llm_suggestions = await self.suggest_llm_optimizations(result.bottlenecks, llm_provider)
                result.suggestions.extend(llm_suggestions)
            except Exception as exc:
                logger.warning("auto_profile LLM enhancement failed: {}", exc)
        return result

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_tests_router() -> APIRouter:
    router = APIRouter()

    @router.post("/api/tests/run")
    async def api_tests_run(body: dict[str, Any]):
        from raven.tools.tests import run_tests

        text = await run_tests(
            path=body.get("path", ""),
            marker=body.get("marker", ""),
            timeout=body.get("timeout", 120),
            extra_args=body.get("extra_args", ""),
        )
        return {"text": text}

    @router.post("/api/tests/coverage")
    async def api_tests_coverage(body: dict[str, Any]):
        from raven.tools.tests import test_coverage

        text = await test_coverage(
            path=body.get("path", ""),
            timeout=body.get("timeout", 180),
        )
        return {"text": text}

    @router.post("/api/tests/generate")
    async def api_tests_generate(body: dict[str, Any]):
        from raven.tools.tests import generate_tests

        text = await generate_tests(file_path=body.get("file_path", ""))
        return {"text": text}

    return router

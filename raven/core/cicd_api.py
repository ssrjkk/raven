from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from loguru import logger

from raven.tools.ci import ci_list_runs, ci_list_workflows, ci_pipeline_status, ci_run_workflow


def create_cicd_router() -> APIRouter:
    router = APIRouter(prefix="/api/cicd", tags=["cicd"])

    @router.get("/workflows")
    async def api_cicd_workflows(owner: str = "", repo: str = "", provider: str = "github"):
        logger.debug("cicd_workflows owner={} repo={} provider={}", owner, repo, provider)
        text = await ci_list_workflows(owner=owner, repo=repo, provider=provider)
        return {"text": text}

    @router.post("/run")
    async def api_cicd_run(body: dict[str, Any]):
        logger.debug("cicd_run {}", body)
        text = await ci_run_workflow(
            workflow_id=body.get("workflow_id", ""),
            owner=body.get("owner", ""),
            repo=body.get("repo", ""),
            ref=body.get("ref", "main"),
            inputs=body.get("inputs", ""),
            provider=body.get("provider", "github"),
        )
        return {"text": text}

    @router.get("/status")
    async def api_cicd_status(pipeline_id: str = "", owner: str = "", repo: str = "", provider: str = "github"):
        logger.debug("cicd_status id={} owner={} repo={}", pipeline_id, owner, repo)
        text = await ci_pipeline_status(pipeline_id=pipeline_id, owner=owner, repo=repo, provider=provider)
        return {"text": text}

    @router.get("/runs")
    async def api_cicd_runs(owner: str = "", repo: str = "", branch: str = "", status: str = "", provider: str = "github"):
        logger.debug("cicd_runs owner={} repo={} branch={} status={}", owner, repo, branch, status)
        text = await ci_list_runs(owner=owner, repo=repo, branch=branch, status=status, provider=provider)
        return {"text": text}

    return router

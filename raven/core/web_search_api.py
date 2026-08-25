from __future__ import annotations

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from raven.core.api_errors import internal_error
from raven.tools.web_search import SearchProvider, WebSearchTool

_tool: WebSearchTool | None = None


async def _get_tool() -> WebSearchTool:
    global _tool
    if _tool is None:
        _tool = WebSearchTool()
    return _tool


class SearchRequest(BaseModel):
    query: str
    provider: str = "duckduckgo"
    max_results: int = 10


class FailoverSearchRequest(BaseModel):
    query: str
    providers: list[str] | None = None
    max_results: int = 10


def create_web_search_router() -> APIRouter:
    router = APIRouter(prefix="/api/web-search", tags=["web-search"])

    @router.post("/search")
    async def api_web_search(req: SearchRequest):
        tool = await _get_tool()
        try:
            provider = SearchProvider(req.provider)
        except ValueError:
            raise HTTPException(400, f"Invalid provider: {req.provider}") from None
        try:
            results = await tool.search(req.query, provider=provider, max_results=req.max_results)
            return {
                "results": [r.model_dump() for r in results],
                "count": len(results),
                "provider": provider.value,
                "query": req.query,
            }
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:
            logger.warning("[web_search] search failed: {}", e)
            raise internal_error(e) from e

    @router.post("/failover")
    async def api_web_search_failover(req: FailoverSearchRequest):
        tool = await _get_tool()
        try:
            providers = [SearchProvider(p) for p in (req.providers or [])] if req.providers else None
            results = await tool.search_with_failover(req.query, providers=providers, max_results=req.max_results)
            return {"results": [r.model_dump() for r in results], "count": len(results), "query": req.query}
        except Exception as e:
            logger.warning("[web_search] failover failed: {}", e)
            raise internal_error(e) from e

    @router.get("/providers")
    async def api_web_search_providers():
        return {"providers": [{"name": p.value, "label": p.name} for p in SearchProvider]}

    return router
